from pathlib import Path

from rich_charts import preprocess_chart_fences


def test_chart_fence_is_replaced_with_ascii_png_reference(tmp_path: Path):
    markdown = """# 테스트

```chart
type: column
title: 인건비 불용액 비교
cat: 2024, 2025
불용액: 2662, 1185
```
"""
    rendered, count = preprocess_chart_fences(markdown, tmp_path)

    assert count == 1
    assert "```chart" not in rendered
    assert "![인건비 불용액 비교](chart_1.png)" in rendered
    assert (tmp_path / "chart_1.png").is_file()
    assert (tmp_path / "chart_1.png").stat().st_size > 0


def test_chart_fence_accepts_thousands_separators(tmp_path: Path):
    markdown = """```chart
type: line
cat: 2024, 2025
불용액: 2,662, 1,185
```"""
    rendered, count = preprocess_chart_fences(markdown, tmp_path)

    assert count == 1
    assert "chart_1.png" in rendered
