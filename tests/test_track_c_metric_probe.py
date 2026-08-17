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


def test_v01_allows_derived_metric_to_disagree_with_aligned_table_and_chart():
    correct = DocumentPlan.model_validate(_derived_metric_plan())
    assert correct.blocks[0].value == "50.0%"

    payload = _derived_metric_plan()
    payload["blocks"][0]["value"] = "40.0%"
    edited = DocumentPlan.model_validate(payload)

    # Evidence probe: table/chart consistency is enforced, but a derived metric
    # is not linked to the underlying values, so a mathematically stale metric
    # can still coexist with 2400 -> 1200 without a validation error.
    assert edited.blocks[0].value == "40.0%"
    assert edited.blocks[1].rows[1][1] == "1200"
    assert edited.blocks[2].series[0].values[1] == 1200
