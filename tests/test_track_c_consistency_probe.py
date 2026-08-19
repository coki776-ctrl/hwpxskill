import pytest
from pydantic import ValidationError

from document_plan import DocumentPlan


def _repeated_fact_plan() -> dict:
    return {
        "version": "0.1",
        "title": "불용액 개선 보고서",
        "preset": "보고서",
        "blocks": [
            {
                "type": "metric",
                "label": "불용액 감소",
                "value": "50.0%",
                "emphasis": "positive",
            },
            {
                "type": "table",
                "caption": "연도별 불용액",
                "headers": ["연도", "불용액"],
                "rows": [["2024", "2400"], ["2025", "1200"]],
            },
            {
                "type": "chart",
                "chart_type": "column",
                "title": "연도별 불용액",
                "categories": ["2024", "2025"],
                "series": [{"name": "불용액", "values": [2400, 1200]}],
            },
        ],
    }


def test_aligned_table_and_chart_with_same_values_remain_valid():
    plan = DocumentPlan.model_validate(_repeated_fact_plan())
    assert plan.blocks[1].rows[1][1] == "1200"
    assert plan.blocks[2].series[0].values[1] == 1200


def test_aligned_table_and_chart_reject_one_copy_of_a_repeated_fact_diverging():
    payload = _repeated_fact_plan()
    payload["blocks"][2]["series"][0]["values"][1] = 1000
    with pytest.raises(ValidationError, match="cross-block data mismatch"):
        DocumentPlan.model_validate(payload)


def test_unrelated_table_and_chart_are_not_forced_to_match():
    payload = _repeated_fact_plan()
    payload["blocks"][2]["title"] = "별도 분석 차트"
    payload["blocks"][2]["series"][0]["values"][1] = 1000
    plan = DocumentPlan.model_validate(payload)
    assert plan.blocks[2].series[0].values[1] == 1000
