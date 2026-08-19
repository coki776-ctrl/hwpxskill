from pathlib import Path

from document_plan import DocumentPlan
from track_c_eval import EvalCase, evaluate_markdown, evaluate_plan, inspect_markdown, load_cases


def _case() -> EvalCase:
    return EvalCase.model_validate(
        {
            "case_id": "demo",
            "title": "데모",
            "prompt": "비교 보고서",
            "source_text": "2024년 100, 2025년 80. 월별 신청으로 개선.",
            "required_terms": ["월별", "개선"],
            "required_numbers": ["100", "80"],
            "expectations": {
                "min_headings": 2,
                "min_tables": 1,
                "min_charts": 1,
                "min_lists": 1,
            },
        }
    )


def _plan() -> DocumentPlan:
    return DocumentPlan.model_validate(
        {
            "version": "0.1",
            "title": "데모",
            "preset": "보고서",
            "blocks": [
                {"type": "heading", "level": 1, "text": "현황"},
                {"type": "paragraph", "text": "월별 신청으로 개선한다."},
                {"type": "list", "ordered": False, "items": ["2024년 100", "2025년 80"]},
                {
                    "type": "table",
                    "headers": ["연도", "값"],
                    "rows": [["2024", "100"], ["2025", "80"]],
                },
                {
                    "type": "chart",
                    "chart_type": "column",
                    "categories": ["2024", "2025"],
                    "series": [{"name": "값", "values": [100, 80]}],
                },
            ],
        }
    )


def test_markdown_feature_inspection_counts_supported_structures():
    markdown = """# 제목

## 현황

- 항목

| 연도 | 값 |
|---|---|
| 2024 | 100 |

```chart
type: column
cat: 2024
값: 100
```
"""
    features = inspect_markdown(markdown)
    assert features.headings == 2
    assert features.tables == 1
    assert features.charts == 1
    assert features.lists == 1


def test_c_plan_is_scored_after_deterministic_mapping():
    result = evaluate_plan(_case(), _plan())
    assert result.mode == "C"
    assert result.fact_coverage == 1.0
    assert result.structure_coverage == 1.0
    assert result.combined_score == 1.0
    assert result.semantic_block_types == ["heading", "paragraph", "list", "table", "chart"]


def test_missing_fact_and_structure_reduce_score_without_hiding_details():
    markdown = "# 데모\n\n## 현황\n\n월별 신청으로 변경한다. 2024년 100."
    result = evaluate_markdown(_case(), markdown, mode="A")
    assert result.fact_coverage < 1.0
    assert result.structure_coverage < 1.0
    assert "개선" in result.missing_terms
    assert "80" in result.missing_numbers
    assert result.features.tables == 0
    assert result.features.charts == 0


def test_track_c_case_pack_contains_five_varied_cases():
    path = Path(__file__).resolve().parents[1] / "track_c_cases.json"
    cases = load_cases(path)
    assert set(cases) == {
        "policy_improvement",
        "budget_execution",
        "facility_status",
        "activity_cost",
        "meeting_action",
    }
    assert cases["meeting_action"].expectations.min_charts == 0
    assert cases["meeting_action"].expectations.max_charts == 0


def test_eval_case_rejects_unexpected_fields():
    payload = _case().model_dump()
    payload["font_policy"] = "blue"
    try:
        EvalCase.model_validate(payload)
    except Exception as exc:
        assert "Extra inputs are not permitted" in str(exc)
    else:
        raise AssertionError("unexpected field should be rejected")


def test_unexpected_numeric_literals_are_reported_but_not_silently_scored_as_facts():
    markdown = """# 데모

## 현황

월별 신청으로 개선한다. 2024년 100, 2025년 80, 추가 추정치 777.
"""
    result = evaluate_markdown(_case(), markdown, mode="A")
    assert "777" in result.unexpected_numbers
    assert "100" not in result.unexpected_numbers


def test_max_chart_expectation_penalizes_unnecessary_chart():
    payload = _case().model_dump()
    payload["expectations"]["min_charts"] = 0
    payload["expectations"]["max_charts"] = 0
    case = EvalCase.model_validate(payload)
    markdown = """# 데모

## 현황

- 월별 개선
- 2024년 100
- 2025년 80

| 연도 | 값 |
|---|---|
| 2024 | 100 |
| 2025 | 80 |

```chart
type: column
cat: 2024, 2025
값: 100, 80
```
"""
    result = evaluate_markdown(case, markdown, mode="A")
    assert result.structure_coverage < 1.0
