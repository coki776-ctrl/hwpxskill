import pytest
from pydantic import ValidationError

from document_plan import DocumentPlan


def _linked_plan() -> dict:
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
                    "to_category": "2025",
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


def test_single_manual_chart_edit_is_rejected_until_linked_values_are_updated():
    DocumentPlan.model_validate(_linked_plan())

    payload = _linked_plan()
    payload["blocks"][2]["series"][0]["values"][1] = 1000

    with pytest.raises(ValidationError, match="cross-block data mismatch"):
        DocumentPlan.model_validate(payload)
