from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from document_plan import DocumentPlan, document_plan_to_markdown


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FeatureExpectations(_StrictModel):
    min_headings: int = Field(default=1, ge=0, le=20)
    min_tables: int = Field(default=0, ge=0, le=10)
    min_charts: int = Field(default=0, ge=0, le=10)
    min_lists: int = Field(default=0, ge=0, le=10)
    max_charts: int | None = Field(default=None, ge=0, le=10)


class EvalCase(_StrictModel):
    case_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=2000)
    source_text: str = Field(min_length=1, max_length=10000)
    required_terms: list[str] = Field(default_factory=list, max_length=30)
    required_numbers: list[str] = Field(default_factory=list, max_length=30)
    expectations: FeatureExpectations = Field(default_factory=FeatureExpectations)


class MarkdownFeatures(_StrictModel):
    headings: int
    tables: int
    charts: int
    lists: int


class EvalResult(_StrictModel):
    case_id: str
    mode: Literal["A", "C"]
    fact_coverage: float
    structure_coverage: float
    combined_score: float
    missing_terms: list[str]
    missing_numbers: list[str]
    features: MarkdownFeatures
    semantic_block_types: list[str] = Field(default_factory=list)
    unexpected_numbers: list[str] = Field(default_factory=list)


_HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")
_CHART_RE = re.compile(r"```chart(?:\s+[^\n]*)?\n.*?\n```", re.IGNORECASE | re.DOTALL)
_LIST_RE = re.compile(r"(?m)^(?:[-*+]\s+\S|\d+[.)]\s+\S)")
_TABLE_DIVIDER_RE = re.compile(
    r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)

_NUMERIC_PATTERNS = (
    re.compile(r"(?<![\w.])\d{1,2}\s*월\s*\d{1,2}\s*일"),
    re.compile(r"(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?\s*%p?"),
    re.compile(r"(?<![\w.])(?:19|20)\d{2}\s*년?"),
    re.compile(r"(?<![\w.])\d{2,}(?:,\d{3})*(?:\.\d+)?"),
)


def _normalize_numeric_token(value: str) -> str:
    return re.sub(r"\s+", "", value).replace(",", "")


def numeric_tokens(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _NUMERIC_PATTERNS:
        for match in pattern.finditer(text):
            token = _normalize_numeric_token(match.group(0))
            if token not in seen:
                seen.add(token)
                found.append(token)
    return found


def _count_tables(markdown: str) -> int:
    return len(_TABLE_DIVIDER_RE.findall(markdown))


def inspect_markdown(markdown: str) -> MarkdownFeatures:
    return MarkdownFeatures(
        headings=len(_HEADING_RE.findall(markdown)),
        tables=_count_tables(markdown),
        charts=len(_CHART_RE.findall(markdown)),
        lists=len(_LIST_RE.findall(markdown)),
    )


def _coverage(required: list[str], text: str) -> tuple[float, list[str]]:
    if not required:
        return 1.0, []
    missing = [item for item in required if item not in text]
    return (len(required) - len(missing)) / len(required), missing


def _structure_score(expected: FeatureExpectations, actual: MarkdownFeatures) -> float:
    checks = [
        (expected.min_headings, actual.headings),
        (expected.min_tables, actual.tables),
        (expected.min_charts, actual.charts),
        (expected.min_lists, actual.lists),
    ]
    criteria: list[float] = [
        min(value / minimum, 1.0)
        for minimum, value in checks
        if minimum > 0
    ]
    if expected.max_charts is not None:
        criteria.append(1.0 if actual.charts <= expected.max_charts else 0.0)
    return sum(criteria) / len(criteria) if criteria else 1.0


def evaluate_markdown(case: EvalCase, markdown: str, *, mode: Literal["A", "C"]) -> EvalResult:
    features = inspect_markdown(markdown)
    term_score, missing_terms = _coverage(case.required_terms, markdown)
    number_score, missing_numbers = _coverage(case.required_numbers, markdown)
    fact_parts = []
    if case.required_terms:
        fact_parts.append(term_score)
    if case.required_numbers:
        fact_parts.append(number_score)
    fact_coverage = sum(fact_parts) / len(fact_parts) if fact_parts else 1.0
    structure_coverage = _structure_score(case.expectations, features)
    source_numbers = set(numeric_tokens(case.source_text))
    output_numbers = numeric_tokens(markdown)
    unexpected_numbers = [token for token in output_numbers if token not in source_numbers]
    return EvalResult(
        case_id=case.case_id,
        mode=mode,
        fact_coverage=round(fact_coverage, 4),
        structure_coverage=round(structure_coverage, 4),
        combined_score=round(0.7 * fact_coverage + 0.3 * structure_coverage, 4),
        missing_terms=missing_terms,
        missing_numbers=missing_numbers,
        features=features,
        unexpected_numbers=unexpected_numbers,
    )


def evaluate_plan(case: EvalCase, plan: DocumentPlan) -> EvalResult:
    markdown = document_plan_to_markdown(plan)
    result = evaluate_markdown(case, markdown, mode="C")
    result.semantic_block_types = [block.type for block in plan.blocks]
    return result


def load_cases(path: Path) -> dict[str, EvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(item) for item in raw]
    return {case.case_id: case for case in cases}


def _load_plan(path: Path) -> DocumentPlan:
    return DocumentPlan.model_validate_json(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare direct Markdown (A) with DocumentPlan->Markdown (C) for Track C."
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--a-markdown", type=Path)
    parser.add_argument("--c-plan", type=Path)
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.case_id not in cases:
        raise SystemExit(f"unknown case_id: {args.case_id}")
    if not args.a_markdown and not args.c_plan:
        raise SystemExit("provide --a-markdown and/or --c-plan")

    case = cases[args.case_id]
    results: list[EvalResult] = []
    if args.a_markdown:
        results.append(
            evaluate_markdown(
                case,
                args.a_markdown.read_text(encoding="utf-8"),
                mode="A",
            )
        )
    if args.c_plan:
        results.append(evaluate_plan(case, _load_plan(args.c_plan)))

    print(json.dumps([item.model_dump() for item in results], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
