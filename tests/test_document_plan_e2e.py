import zipfile

import app
from document_plan import DocumentPlan, document_plan_to_markdown
from kordoc_engine import generate_hwpx
from rich_charts import preprocess_chart_fences


def test_document_plan_reaches_valid_hwpx_through_proven_kordoc_pipeline(tmp_path):
    plan = DocumentPlan.model_validate(
        {
            "version": "0.1",
            "title": "트랙 C 통합 검증 보고서",
            "preset": "보고서",
            "blocks": [
                {"type": "heading", "level": 1, "text": "지원 방식 개선"},
                {
                    "type": "paragraph",
                    "text": "분기별 신청을 월별 신청으로 전환한 효과를 비교합니다.",
                },
                {
                    "type": "metric",
                    "label": "불용액 감소",
                    "value": "50.0%",
                    "emphasis": "positive",
                },
                {
                    "type": "table",
                    "caption": "연도별 비교",
                    "headers": ["구분", "2024", "2025"],
                    "rows": [["불용액", "2400", "1200"]],
                },
                {
                    "type": "chart",
                    "chart_type": "column",
                    "title": "연도별 불용액 비교",
                    "categories": ["2024", "2025"],
                    "series": [{"name": "불용액", "values": [2400, 1200]}],
                },
            ],
        }
    )

    semantic_markdown = document_plan_to_markdown(plan)
    assert "```chart" in semantic_markdown
    assert "| 구분 | 2024 | 2025 |" in semantic_markdown

    rendered_markdown, chart_count = preprocess_chart_fences(semantic_markdown, tmp_path)
    assert chart_count == 1
    assert "```chart" not in rendered_markdown
    assert "chart_1.png" in rendered_markdown

    chart_bytes = (tmp_path / "chart_1.png").read_bytes()
    markdown_path = tmp_path / "input.md"
    output_path = tmp_path / "track_c_e2e.hwpx"
    markdown_path.write_text(rendered_markdown, encoding="utf-8")

    result = generate_hwpx(markdown_path, output_path, preset=plan.preset, timeout=120)
    assert result.ok, result.diagnostic

    app.add_hancom_compatibility_metadata(output_path)
    assert app.validate_hwpx(str(output_path)) == []

    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        section = archive.read("Contents/section0.xml").decode("utf-8")
        embedded_pngs = [archive.read(name) for name in names if name.lower().endswith(".png")]

        assert "트랙 C 통합 검증 보고서" in section
        assert "지원 방식 개선" in section
        assert "불용액 감소" in section
        assert "2400" in section
        assert "1200" in section
        assert section.count("<hp:tbl") >= 1
        assert any(data == chart_bytes for data in embedded_pngs)
        assert "version.xml" in names
        assert "settings.xml" in names
