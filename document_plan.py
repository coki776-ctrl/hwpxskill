from __future__ import annotations

import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HeadingBlock(_StrictModel):
    type: Literal["heading"]
    text: str = Field(min_length=1, max_length=200)
    level: int = Field(default=1, ge=1, le=3)


class ParagraphBlock(_StrictModel):
    type: Literal["paragraph"]
    text: str = Field(min_length=1, max_length=5000)


class ListBlock(_StrictModel):
    type: Literal["list"]
    items: list[str] = Field(min_length=1, max_length=30)
    ordered: bool = False

    @field_validator("items")
    @classmethod
    def validate_items(cls, items: list[str]) -> list[str]:
        normalized = [item.strip() for item in items]
        if any(not item for item in normalized):
            raise ValueError("list items must not be empty")
        return normalized


class CalloutBlock(_StrictModel):
    type: Literal["callout"]
    text: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=100)


class MetricDerivation(_StrictModel):
    kind: Literal["percent_decrease"]
    source_chart_title: str = Field(min_length=1, max_length=200)
    series: str = Field(min_length=1, max_length=80)
    from_category: str = Field(min_length=1, max_length=100)
    to_category: str = Field(min_length=1, max_length=100)


class MetricBlock(_StrictModel):
    type: Literal["metric"]
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=80)
    emphasis: Literal["positive", "negative", "neutral"] = "neutral"
    derivation: MetricDerivation | None = None


class TableBlock(_StrictModel):
    type: Literal["table"]
    headers: list[str] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(min_length=1, max_length=100)
    caption: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_shape(self) -> "TableBlock":
        width = len(self.headers)
        if any(not str(header).strip() for header in self.headers):
            raise ValueError("table headers must not be empty")
        for index, row in enumerate(self.rows, start=1):
            if len(row) != width:
                raise ValueError(
                    f"table row {index} has {len(row)} cells; expected {width}"
                )
        return self


class ChartSeries(_StrictModel):
    name: str = Field(min_length=1, max_length=80)
    values: list[float] = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        if ":" in name or "：" in name:
            raise ValueError("chart series name must not contain ':' or '：'")
        return name

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: list[float]) -> list[float]:
        if any(not math.isfinite(value) for value in values):
            raise ValueError("chart values must be finite numbers")
        return values


class ChartBlock(_StrictModel):
    type: Literal["chart"]
    chart_type: Literal["column", "bar", "line", "pie", "doughnut", "area"]
    categories: list[str] = Field(min_length=1, max_length=50)
    series: list[ChartSeries] = Field(min_length=1, max_length=8)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, categories: list[str]) -> list[str]:
        normalized = [item.strip() for item in categories]
        if any(not item for item in normalized):
            raise ValueError("chart categories must not be empty")
        if any("," in item for item in normalized):
            raise ValueError(
                "chart categories must not contain commas because the current chart fence uses comma separators"
            )
        return normalized

    @model_validator(mode="after")
    def validate_series_shape(self) -> "ChartBlock":
        expected = len(self.categories)
        for series in self.series:
            if len(series.values) != expected:
                raise ValueError(
                    f"chart series '{series.name}' has {len(series.values)} values; expected {expected}"
                )
        if self.chart_type in {"pie", "doughnut"} and len(self.series) != 1:
            raise ValueError("pie and doughnut charts require exactly one series")
        return self


DocumentBlock = Annotated[
    HeadingBlock
    | ParagraphBlock
    | ListBlock
    | CalloutBlock
    | MetricBlock
    | TableBlock
    | ChartBlock,
    Field(discriminator="type"),
]


def _parse_numeric_cell(value: str) -> float | None:
    normalized = value.strip().replace(",", "")
    if normalized.endswith("%"):
        normalized = normalized[:-1].strip()
    try:
        number = float(normalized)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _aligned_table_chart_errors(blocks: list[DocumentBlock]) -> list[str]:
    """Check only strongly aligned table/chart pairs.

    The rule intentionally stays narrow: caption/title must match exactly, the
    table's first column must exactly match chart categories, and a table header
    must exactly match a chart series name. Only then are numeric values compared.
    """
    tables = [block for block in blocks if isinstance(block, TableBlock) and block.caption]
    charts = [block for block in blocks if isinstance(block, ChartBlock) and block.title]
    errors: list[str] = []

    for table in tables:
        if len(table.headers) < 2:
            continue
        table_categories = [row[0].strip() for row in table.rows]
        for chart in charts:
            if table.caption != chart.title or table_categories != chart.categories:
                continue
            for series in chart.series:
                if series.name not in table.headers[1:]:
                    continue
                column = table.headers.index(series.name)
                table_values = [_parse_numeric_cell(row[column]) for row in table.rows]
                if any(value is None for value in table_values):
                    continue
                for category, table_value, chart_value in zip(
                    chart.categories, table_values, series.values
                ):
                    if not math.isclose(float(table_value), chart_value, rel_tol=1e-9, abs_tol=1e-9):
                        errors.append(
                            "cross-block data mismatch for "
                            f"'{table.caption}' / '{series.name}' / '{category}': "
                            f"table={table_value:g}, chart={chart_value:g}"
                        )
    return errors


def _derived_metric_errors(blocks: list[DocumentBlock]) -> list[str]:
    """Validate only metrics that explicitly declare a supported derivation."""
    charts = [block for block in blocks if isinstance(block, ChartBlock)]
    errors: list[str] = []

    for metric in [block for block in blocks if isinstance(block, MetricBlock) and block.derivation]:
        derivation = metric.derivation
        assert derivation is not None
        matching_charts = [
            chart for chart in charts if chart.title == derivation.source_chart_title
        ]
        if len(matching_charts) != 1:
            errors.append(
                f"derived metric '{metric.label}' requires exactly one source chart "
                f"titled '{derivation.source_chart_title}'"
            )
            continue
        chart = matching_charts[0]

        matching_series = [series for series in chart.series if series.name == derivation.series]
        if len(matching_series) != 1:
            errors.append(
                f"derived metric '{metric.label}' requires exactly one series "
                f"named '{derivation.series}'"
            )
            continue
        series = matching_series[0]

        if chart.categories.count(derivation.from_category) != 1:
            errors.append(
                f"derived metric '{metric.label}' requires unique from_category "
                f"'{derivation.from_category}'"
            )
            continue
        if chart.categories.count(derivation.to_category) != 1:
            errors.append(
                f"derived metric '{metric.label}' requires unique to_category "
                f"'{derivation.to_category}'"
            )
            continue

        from_index = chart.categories.index(derivation.from_category)
        to_index = chart.categories.index(derivation.to_category)
        from_value = series.values[from_index]
        to_value = series.values[to_index]

        if derivation.kind == "percent_decrease":
            if from_value <= 0:
                errors.append(
                    f"derived metric '{metric.label}' percent_decrease requires a positive starting value"
                )
                continue
            if to_value > from_value:
                errors.append(
                    f"derived metric '{metric.label}' percent_decrease source values do not decrease"
                )
                continue
            if not metric.value.strip().endswith("%"):
                errors.append(
                    f"derived metric '{metric.label}' percent_decrease value must be a percentage"
                )
                continue
            actual = _parse_numeric_cell(metric.value)
            if actual is None:
                errors.append(
                    f"derived metric '{metric.label}' value is not numeric"
                )
                continue
            expected = (from_value - to_value) / from_value * 100.0
            if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=0.05):
                errors.append(
                    f"derived metric mismatch for '{metric.label}': "
                    f"value={actual:g}%, expected={expected:.6g}% from "
                    f"'{derivation.source_chart_title}' / '{derivation.series}' / "
                    f"'{derivation.from_category}' -> '{derivation.to_category}'"
                )
    return errors


class DocumentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal["0.1"] = "0.1"
    title: str = Field(min_length=1, max_length=200)
    preset: Literal["보고서", "기안문", "계획서", "통지", "회의록", "개조식", "보도자료"] = "보고서"
    blocks: list[DocumentBlock] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def validate_cross_block_consistency(self) -> "DocumentPlan":
        errors = _aligned_table_chart_errors(self.blocks)
        errors.extend(_derived_metric_errors(self.blocks))
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _format_percentage_like(template: str, value: float) -> str:
    match = re.fullmatch(r"[+-]?\d+(?:\.(\d+))?%", template.strip())
    decimals = len(match.group(1) or "") if match else 1
    return f"{value:.{decimals}f}%"


def update_linked_chart_value(
    plan: DocumentPlan,
    *,
    chart_title: str,
    series_name: str,
    category: str,
    value: float,
) -> DocumentPlan:
    """Update one chart data point and deterministic strongly linked copies.

    Only exact relationships already represented by the validated plan are
    propagated: strongly aligned tables and metrics with explicit derivations.
    The input plan is not mutated.
    """
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError("edit value must be a finite number")

    matching_chart_indexes = [
        index
        for index, block in enumerate(plan.blocks)
        if isinstance(block, ChartBlock) and block.title == chart_title
    ]
    if len(matching_chart_indexes) != 1:
        raise ValueError(f"expected exactly one chart titled '{chart_title}'")
    chart_index = matching_chart_indexes[0]
    chart = plan.blocks[chart_index]
    assert isinstance(chart, ChartBlock)

    matching_series_indexes = [
        index for index, series in enumerate(chart.series) if series.name == series_name
    ]
    if len(matching_series_indexes) != 1:
        raise ValueError(
            f"expected exactly one series named '{series_name}' in chart '{chart_title}'"
        )
    series_index = matching_series_indexes[0]

    if chart.categories.count(category) != 1:
        raise ValueError(
            f"expected exactly one category '{category}' in chart '{chart_title}'"
        )
    category_index = chart.categories.index(category)

    payload = plan.model_dump()
    payload["blocks"][chart_index]["series"][series_index]["values"][category_index] = numeric_value

    formatted_value = str(int(numeric_value)) if numeric_value.is_integer() else format(numeric_value, ".12g")
    for block_index, block in enumerate(plan.blocks):
        if not isinstance(block, TableBlock) or block.caption != chart_title:
            continue
        if len(block.headers) < 2:
            continue
        table_categories = [row[0].strip() for row in block.rows]
        if table_categories != chart.categories:
            continue
        if block.headers.count(series_name) != 1:
            if series_name in block.headers:
                raise ValueError(
                    f"linked table '{chart_title}' has ambiguous header '{series_name}'"
                )
            continue
        column = block.headers.index(series_name)
        payload["blocks"][block_index]["rows"][category_index][column] = formatted_value

    updated_series_values = payload["blocks"][chart_index]["series"][series_index]["values"]
    for block_index, block in enumerate(plan.blocks):
        if not isinstance(block, MetricBlock) or block.derivation is None:
            continue
        derivation = block.derivation
        if (
            derivation.source_chart_title != chart_title
            or derivation.series != series_name
            or derivation.kind != "percent_decrease"
        ):
            continue
        from_index = chart.categories.index(derivation.from_category)
        to_index = chart.categories.index(derivation.to_category)
        from_value = float(updated_series_values[from_index])
        to_value = float(updated_series_values[to_index])
        if from_value > 0 and to_value <= from_value:
            expected = (from_value - to_value) / from_value * 100.0
            payload["blocks"][block_index]["value"] = _format_percentage_like(
                block.value, expected
            )

    return DocumentPlan.model_validate(payload)


def assign_block_ids(plan: DocumentPlan) -> list[dict]:
    """Return normalized block dictionaries with deterministic internal IDs."""
    return [
        {"block_id": f"b{index:03d}", **block.model_dump()}
        for index, block in enumerate(plan.blocks, start=1)
    ]


def _escape_table_cell(value: object) -> str:
    flattened = " ".join(str(value).splitlines())
    return flattened.replace("\\", "\\\\").replace("|", "\\|")


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def document_plan_to_markdown(plan: DocumentPlan) -> str:
    """Map a validated semantic plan to the existing rich Markdown/chart-fence input."""
    chunks: list[str] = [f"# {plan.title}"]

    for block in plan.blocks:
        if isinstance(block, HeadingBlock):
            chunks.append(f"{'#' * (block.level + 1)} {block.text}")
        elif isinstance(block, ParagraphBlock):
            chunks.append(block.text)
        elif isinstance(block, ListBlock):
            if block.ordered:
                chunks.append("\n".join(f"{index}. {item}" for index, item in enumerate(block.items, start=1)))
            else:
                chunks.append("\n".join(f"- {item}" for item in block.items))
        elif isinstance(block, CalloutBlock):
            if block.title:
                chunks.append(f"**{block.title}**\n\n{block.text}")
            else:
                chunks.append(f"**핵심**\n\n{block.text}")
        elif isinstance(block, MetricBlock):
            metric_heading = {
                "positive": "핵심 지표 · 개선",
                "negative": "핵심 지표 · 주의",
                "neutral": "핵심 지표",
            }[block.emphasis]
            chunks.append(f"**{metric_heading}**\n\n**{block.label}: {block.value}**")
        elif isinstance(block, TableBlock):
            lines: list[str] = []
            if block.caption:
                lines.append(f"**{block.caption}**")
                lines.append("")
            lines.append("| " + " | ".join(_escape_table_cell(item) for item in block.headers) + " |")
            lines.append("|" + "|".join("---" for _ in block.headers) + "|")
            for row in block.rows:
                lines.append("| " + " | ".join(_escape_table_cell(item) for item in row) + " |")
            chunks.append("\n".join(lines))
        elif isinstance(block, ChartBlock):
            lines = ["```chart", f"type: {block.chart_type}"]
            if block.title:
                lines.append(f"title: {block.title}")
            lines.append("cat: " + ", ".join(block.categories))
            for series in block.series:
                lines.append(
                    f"{series.name}: " + ", ".join(_format_number(value) for value in series.values)
                )
            lines.append("```")
            chunks.append("\n".join(lines))
        else:  # pragma: no cover
            raise TypeError(f"Unsupported document block: {type(block).__name__}")

    return "\n\n".join(chunks).rstrip() + "\n"
