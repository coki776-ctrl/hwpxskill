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


def test_v01_schema_allows_one_copy_of_a_repeated_fact_to_diverge():
    original = DocumentPlan.model_validate(_repeated_fact_plan())
    assert original.blocks[1].rows[1][1] == "1200"
    assert original.blocks[2].series[0].values[1] == 1200

    payload = _repeated_fact_plan()
    payload["blocks"][2]["series"][0]["values"][1] = 1000
    edited = DocumentPlan.model_validate(payload)

    # Evidence probe: v0.1 validates block shapes independently, so a stale table
    # value and an edited chart value can coexist without a validation error.
    assert edited.blocks[1].rows[1][1] == "1200"
    assert edited.blocks[2].series[0].values[1] == 1000
