from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

_CHART_FENCE_RE = re.compile(
    r"```chart(?:\s+[^\n]*)?\n(?P<body>.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)
_RESERVED_KEYS = {"type", "cat", "size", "colors", "point_colors", "title"}

_FONT_READY = False
_FONT_FAMILY: str | None = None


def _configure_korean_font() -> str:
    global _FONT_READY, _FONT_FAMILY
    if _FONT_READY:
        if _FONT_FAMILY is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Korean chart font state is invalid")
        return _FONT_FAMILY

    candidates = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            font_manager.fontManager.addfont(str(path))
            family = font_manager.FontProperties(fname=str(path)).get_name()
            plt.rcParams["font.family"] = family
            _FONT_FAMILY = family
            break
        except Exception:
            continue

    if _FONT_FAMILY is None:
        raise RuntimeError(
            "Korean chart font not found. Install fonts-noto-cjk or provide "
            "NotoSansCJK/NanumGothic at a supported path."
        )

    plt.rcParams["axes.unicode_minus"] = False
    _FONT_READY = True
    return _FONT_FAMILY


def _parse_number_list(value: str) -> list[float]:
    # Kordoc-style chart input commonly uses comma separators. Remove commas that
    # are clearly thousands separators before splitting series values.
    normalized = re.sub(r"(\d),(?=\d{3}(?:\D|$))", r"\1", value)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if not parts:
        raise ValueError("chart series has no numeric values")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"chart series contains a non-numeric value: {value}") from exc


def _parse_chart_fence(body: str) -> dict:
    chart_type = "column"
    categories: list[str] = []
    title = ""
    series: list[tuple[str, list[float]]] = []

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.search(r"[:：]", line)
        if match is None or match.start() <= 0:
            continue
        key = line[: match.start()].strip()
        value = line[match.start() + 1 :].strip()
        lower = key.lower()

        if lower == "type":
            chart_type = value.lower() or "column"
        elif lower == "cat":
            categories = [item.strip() for item in value.split(",") if item.strip()]
        elif lower == "title":
            title = value
        elif lower in _RESERVED_KEYS:
            # PNG fallback currently lets matplotlib choose colors/size.
            continue
        else:
            series.append((key, _parse_number_list(value)))

    if not series:
        raise ValueError("chart fence must include at least one data series")

    max_points = max(len(values) for _, values in series)
    if not categories:
        categories = [f"항목 {index + 1}" for index in range(max_points)]
    elif len(categories) < max_points:
        categories.extend(
            f"항목 {index + 1}" for index in range(len(categories), max_points)
        )

    normalized_series: list[tuple[str, list[float]]] = []
    for name, values in series:
        padded = values[: len(categories)]
        if len(padded) < len(categories):
            padded = padded + [0.0] * (len(categories) - len(padded))
        normalized_series.append((name, padded))

    aliases = {
        "col": "column",
        "세로막대": "column",
        "막대": "column",
        "가로막대": "bar",
        "선": "line",
        "꺾은선": "line",
        "원": "pie",
        "파이": "pie",
        "donut": "doughnut",
        "도넛": "doughnut",
        "영역": "area",
    }
    chart_type = aliases.get(chart_type, chart_type)
    supported = {"column", "bar", "line", "pie", "doughnut", "area"}
    if chart_type not in supported:
        raise ValueError(
            f"unsupported chart type for PNG fallback: {chart_type}. "
            f"Use one of {', '.join(sorted(supported))}."
        )

    return {
        "type": chart_type,
        "title": title,
        "categories": categories,
        "series": normalized_series,
    }


def _render_chart_png(spec: dict, output: Path) -> None:
    _configure_korean_font()
    categories: list[str] = spec["categories"]
    series: list[tuple[str, list[float]]] = spec["series"]
    chart_type: str = spec["type"]
    title: str = spec["title"]

    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=160)
    try:
        if chart_type in {"pie", "doughnut"}:
            name, values = series[0]
            kwargs = {"wedgeprops": {"width": 0.42}} if chart_type == "doughnut" else {}
            ax.pie(values, labels=categories, autopct="%1.1f%%", startangle=90, **kwargs)
            ax.axis("equal")
            if not title:
                title = name
        elif chart_type == "line":
            x = list(range(len(categories)))
            for name, values in series:
                ax.plot(x, values, marker="o", label=name)
            ax.set_xticks(x, categories)
            if len(series) > 1:
                ax.legend()
            ax.grid(axis="y", alpha=0.25)
        elif chart_type == "area":
            x = list(range(len(categories)))
            for name, values in series:
                ax.plot(x, values, label=name)
                ax.fill_between(x, values, alpha=0.2)
            ax.set_xticks(x, categories)
            if len(series) > 1:
                ax.legend()
            ax.grid(axis="y", alpha=0.25)
        else:
            count = max(1, len(series))
            base = list(range(len(categories)))
            width = min(0.72 / count, 0.36)
            offsets = [(index - (count - 1) / 2) * width for index in range(count)]
            for series_index, (name, values) in enumerate(series):
                positions = [x + offsets[series_index] for x in base]
                if chart_type == "bar":
                    ax.barh(positions, values, height=width, label=name)
                else:
                    ax.bar(positions, values, width=width, label=name)
            if chart_type == "bar":
                ax.set_yticks(base, categories)
                ax.grid(axis="x", alpha=0.25)
            else:
                ax.set_xticks(base, categories)
                ax.grid(axis="y", alpha=0.25)
            if len(series) > 1:
                ax.legend()

        if title:
            ax.set_title(title)
        fig.tight_layout()
        fig.savefig(output, bbox_inches="tight")
    finally:
        plt.close(fig)


def preprocess_chart_fences(markdown: str, workdir: Path) -> tuple[str, int]:
    """Replace Kordoc native ```chart fences with embedded PNG references.

    The returned Markdown uses ASCII-only chart filenames so Kordoc --image-dir
    will embed the image bytes instead of leaving a placeholder.
    """
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        spec = _parse_chart_fence(match.group("body"))
        count += 1
        filename = f"chart_{count}.png"
        _render_chart_png(spec, workdir / filename)
        alt = spec["title"] or (spec["series"][0][0] if spec["series"] else f"chart {count}")
        title_line = f"**{spec['title']}**\n\n" if spec["title"] else ""
        return f"{title_line}![{alt}]({filename})"

    rendered = _CHART_FENCE_RE.sub(replace, markdown)
    return rendered, count
