# Kordoc migration plan

## Target architecture

`Custom GPT Action -> FastAPI orchestration -> Kordoc -> validation/layout checks -> download URL`

FastAPI should own authentication, request validation, temporary file/job management, download URLs, and lightweight post-generation checks. Kordoc should own HWPX rendering.

## Phase 1: completed in this branch

- Pin a published Kordoc version in the Render image.
- Fail the Docker build early if `kordoc --version` is unavailable.
- Add `kordoc_engine.py` as the single CLI boundary.
- Route the deployed rich-document app through `rich_action_kordoc.py` without deleting the legacy path.
- Keep chart preprocessing, Action endpoints, job handling, download URLs, Hancom compatibility metadata, and current validation in place.
- Add tests for Kordoc command construction and failure handling.

## Keep for now

- `action_ext.py`: Action/API orchestration.
- `rich_action_ext.py`: stable route/job/download implementation during migration.
- `rich_charts.py`: chart PNG preprocessing until Kordoc provides an equivalent path that meets report-quality requirements.
- `content_guard.py`, `page_guard.py`, `gonmun_lint.py`: quality/business rules are not rendering-engine responsibilities.
- existing templates and tests: regression assets.

## Replace only after parity tests

The following low-level HWPX responsibilities should not be extended further. Retire them only when the equivalent Kordoc path has passed real Hancom Office tests.

- `scripts/create_document.py`: custom Markdown/JSON -> HWPX rendering.
- `scripts/build_hwpx.py`: manual HWPX ZIP/XML assembly.
- `scripts/edit_hwpx.py`: low-level HWPX editing where Kordoc patch/fill can cover the use case.
- `scripts/analyze_template.py` and `scripts/hwpx_slots.py`: migrate where Kordoc profile/form tooling provides equivalent results.
- `scripts/fix_namespaces.py`: remove if no longer required by Kordoc-produced output.
- duplicated structural validation: reduce to API-level safety checks after Kordoc validation is adopted.

## Do not delete yet

No legacy renderer is removed in Phase 1. The rollback path remains switching the Docker entrypoint from `rich_action_kordoc:app` back to `rich_action_ext:app`.

## Acceptance gate before deleting legacy code

1. Plain Korean paragraphs and headings open normally in Hancom Office.
2. Markdown tables preserve expected text and dimensions.
3. PNG charts are embedded and visible.
4. The `보고서` preset produces acceptable public-sector styling.
5. Generated HWPX passes structural validation.
6. Existing synchronous and job Action endpoints return valid download URLs.
7. At least one real report and one existing-template edit are manually checked in Hancom Office.

Only after these gates pass should duplicated renderer/XML code be removed.
