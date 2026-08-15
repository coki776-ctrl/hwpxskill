from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from app import (
    ActionFileRef,
    app,
    download_action_hwpx,
    require_api_key,
    select_action_hwpx,
    validate_hwpx,
)
from hwpx_slots import iter_slots, summarize_slots


class ActionInspectSummaryRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    include_empty_cells: bool = False


class InspectSummaryResponse(BaseModel):
    ok: bool
    source: str
    total_slots: int
    paragraph_slots: int
    cell_slots: int


class CompactSlot(BaseModel):
    key: str
    kind: str
    max_chars: int
    preview: str
    table: int | None = None
    row: int | None = None
    col: int | None = None
    occurrence: int | None = None
    empty: bool | None = None


class FindResponse(BaseModel):
    ok: bool
    source: str
    search_text: str
    matched_slots: int
    returned: int
    truncated: bool
    slots: list[CompactSlot]


class ActionFindRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    search_text: str = Field(min_length=1, max_length=200)
    include_empty_cells: bool = False
    preview_len: int = Field(default=80, ge=20, le=120)
    limit: int = Field(default=10, ge=1, le=10)


class ActionInspectPageRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    include_empty_cells: bool = False
    preview_len: int = Field(default=40, ge=10, le=80)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=5, ge=1, le=10)
    search_text: str | None = Field(default=None, max_length=200)


def _compact_slot(slot: dict) -> dict:
    compact = {
        "key": slot.get("key"),
        "kind": slot.get("kind"),
        "max_chars": slot.get("max_chars"),
        "preview": slot.get("preview", ""),
    }
    for name in ("table", "row", "col", "occurrence", "empty"):
        if name in slot:
            compact[name] = slot[name]
    return compact


def _load_hwpx(refs: list[ActionFileRef]):
    ref = select_action_hwpx(refs)
    temp = tempfile.TemporaryDirectory(prefix="hwpx-action-inspect-")
    src = Path(temp.name) / "input.hwpx"
    download_action_hwpx(ref, src)
    errors = validate_hwpx(str(src))
    if errors:
        temp.cleanup()
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    return ref, src, temp


@app.post(
    "/action/inspect-summary",
    operation_id="inspectHwpx",
    dependencies=[Depends(require_api_key)],
    response_model=InspectSummaryResponse,
)
def action_inspect_hwpx_summary(payload: ActionInspectSummaryRequest) -> InspectSummaryResponse:
    ref, src, temp = _load_hwpx(payload.openaiFileIdRefs)
    try:
        return InspectSummaryResponse(**{
            "ok": True,
            "source": ref.name,
            **summarize_slots(src, include_empty_cells=payload.include_empty_cells),
        })
    finally:
        temp.cleanup()


@app.post(
    "/action/find",
    operation_id="findHwpxText",
    dependencies=[Depends(require_api_key)],
    response_model=FindResponse,
)
def action_find_hwpx_text(payload: ActionFindRequest) -> FindResponse:
    ref, src, temp = _load_hwpx(payload.openaiFileIdRefs)
    try:
        needle = payload.search_text.casefold()
        matched = 0
        shown = []
        for slot in iter_slots(src, payload.preview_len, payload.include_empty_cells):
            if needle not in str(slot.get("preview", "")).casefold():
                continue
            matched += 1
            if len(shown) < payload.limit:
                shown.append(slot)
        return FindResponse(**{
            "ok": True,
            "source": ref.name,
            "search_text": payload.search_text,
            "matched_slots": matched,
            "returned": len(shown),
            "truncated": matched > len(shown),
            "slots": [_compact_slot(slot) for slot in shown],
        })
    finally:
        temp.cleanup()


@app.post(
    "/action/inspect-page",
    operation_id="inspectHwpxPage",
    dependencies=[Depends(require_api_key)],
)
def action_inspect_hwpx_page(payload: ActionInspectPageRequest) -> dict:
    ref, src, temp = _load_hwpx(payload.openaiFileIdRefs)
    try:
        all_slots = list(iter_slots(src, payload.preview_len, payload.include_empty_cells))
        filtered = all_slots
        query = (payload.search_text or "").strip()
        if query:
            needle = query.casefold()
            filtered = [
                slot for slot in all_slots
                if needle in str(slot.get("preview", "")).casefold()
            ]
        start = min(payload.offset, len(filtered))
        end = min(start + payload.limit, len(filtered))
        page = filtered[start:end]
        return {
            "ok": True,
            "source": ref.name,
            "matched_slots": len(filtered),
            "offset": start,
            "returned": len(page),
            "has_more": end < len(filtered),
            "next_offset": end if end < len(filtered) else None,
            "slots": [_compact_slot(slot) for slot in page],
        }
    finally:
        temp.cleanup()

