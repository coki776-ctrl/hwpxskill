import pytest
from pydantic import ValidationError

from document_plan import DocumentPlan, assign_block_ids, document_plan_to_markdown


def _valid_plan() -> dict:
    return {
        "version": "0.1",
        "title": "사립학교 인건비 지원방법 개선",
        "preset": "보고서",
        "blocks": [
            {"type": "heading", "level": 1, "text": "추진 배경"},
            {"type": "paragraph", "text": "분기별 신청 방식을 월별 신청으로 개선했습니다."},
            {
                "type": "list",
                "ordered": False,
                "items": ["신청 주기 단축", "집행 예측 가능성 향상"],
            },
            {
                "type": "callout",
                "title": "핵심",
                "text": "실제 수요에 가까운 월별 신청으로 불용 발생 가능성을 줄입니다.",
            },
            {
                "type": "metric",
                "label": "불용액 감소",
                "value": "55.5%",
                "emphasis": "positive",
            },
            {
                "type": "table",
                "caption": "신청 방식 비교",
                "headers": ["구분", "기존", "개선"],
                "rows": [["신청", "분기별", "월별"], ["정산", "사후", "수시"]],
            },
            {
                "type": "chart",
                "chart_type": "column",
                "title": "연도별 불용액 비교",
                "categories": ["2024", "2025"],
                "series": [{"name": "불용액", "values": [2662, 1185]}],
            },
        ],
    }


def test_valid_plan_maps_to_existing_markdown_and_chart_fence():
    plan = DocumentPlan.model_validate(_valid_plan())

    markdown = document_plan_to_markdown(plan)

    assert markdown.startswith("# 사립학교 인건비 지원방법 개선\n")
    assert "## 추진 배경" in markdown
    assert "- 신청 주기 단축" in markdown
    assert "**핵심**" in markdown
    assert "**핵심 지표 · 개선**" in markdown
    assert "**불용액 감소: 55.5%**" in markdown
    assert "| 구분 | 기존 | 개선 |" in markdown
    assert "```chart" in markdown
    assert "type: column" in markdown
    assert "cat: 2024, 2025" in markdown
    assert "불용액: 2662, 1185" in markdown


def test_assign_block_ids_is_deterministic_and_not_part_of_llm_schema():
    plan = DocumentPlan.model_validate(_valid_plan())

    blocks = assign_block_ids(plan)

    assert [block["block_id"] for block in blocks] == [
        "b001",
        "b002",
        "b003",
        "b004",
        "b005",
        "b006",
        "b007",
    ]
    assert "block_id" not in DocumentPlan.model_json_schema()["$defs"]["HeadingBlock"]["properties"]


def test_extra_fields_are_rejected():
    payload = _valid_plan()
    payload["blocks"][0]["font_size"] = 18

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DocumentPlan.model_validate(payload)


def test_table_shape_mismatch_is_rejected():
    payload = _valid_plan()
    payload["blocks"][5]["rows"][0] = ["신청", "분기별"]

    with pytest.raises(ValidationError, match="expected 3"):
        DocumentPlan.model_validate(payload)


def test_chart_series_length_mismatch_is_rejected():
    payload = _valid_plan()
    payload["blocks"][6]["series"][0]["values"] = [2662]

    with pytest.raises(ValidationError, match="expected 2"):
        DocumentPlan.model_validate(payload)


def test_chart_fence_incompatible_delimiters_are_rejected():
    payload = _valid_plan()
    payload["blocks"][6]["categories"] = ["2024, 상반기", "2025"]

    with pytest.raises(ValidationError, match="must not contain commas"):
        DocumentPlan.model_validate(payload)

    payload = _valid_plan()
    payload["blocks"][6]["series"][0]["name"] = "불용액: 결산"

    with pytest.raises(ValidationError, match="must not contain"):
        DocumentPlan.model_validate(payload)


def test_pie_requires_exactly_one_series():
    payload = _valid_plan()
    payload["blocks"][6]["chart_type"] = "pie"
    payload["blocks"][6]["series"].append({"name": "추가", "values": [1, 2]})

    with pytest.raises(ValidationError, match="exactly one series"):
        DocumentPlan.model_validate(payload)


def test_markdown_table_cells_escape_pipe_characters():
    payload = _valid_plan()
    payload["blocks"][5]["rows"][0][2] = "월별 | 수시"

    markdown = document_plan_to_markdown(DocumentPlan.model_validate(payload))

    assert "월별 \\| 수시" in markdown
