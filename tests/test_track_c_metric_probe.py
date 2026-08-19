import pytest
from pydantic import ValidationError

from document_plan import DocumentPlan


def _derived_metric_plan() -> dict:
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
                "derivation": {
                    "kind": "percent_decrease",
                    "source_chart_title": "연도별 불용액",
                    "series": "불용액",
                    "from_category": "2024",
                    "to_category": "2025"
                },
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


def test_explicit_percent_decrease_derivation_accepts_correct_metric():
    plan = DocumentPlan.model_validate(_derived_metric_plan())
    assert plan.blocks[0].value == "50.0%"


def test_explicit_percent_decrease_derivation_rejects_stale_metric():
    payload = _derived_metric_plan()
    payload["blocks"][0]["value"] = "40.0%"

    with pytest.raises(ValidationError, match="derived metric mismatch"):
        DocumentPlan.model_validate(payload)


def test_unbound_metric_is_not_guessed_from_neighboring_chart():
    payload = _derived_metric_plan()
    payload["blocks"][0].pop("derivation")
    payload["blocks"][0]["value"] = "40.0%"

    plan = DocumentPlan.model_validate(payload)

    # No fuzzy label/title inference: only an explicitly bound metric is checked.
    assert plan.blocks[0].value == "40.0%"
