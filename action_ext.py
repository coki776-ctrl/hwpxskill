from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from app import (
    ActionFileRef,
    app,
    collect_slots,
    download_action_hwpx,
    require_api_key,
    select_action_hwpx,
    validate_hwpx,
)


class ActionInspectSummaryRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    include_empty_cells: bool = False
    preview_len: int = Field(default=40, ge=10, le=80)


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


def _load_slots(refs: list[ActionFileRef], include_empty_cells: bool, preview_len: int):
    ref = select_action_hwpx(refs)
    temp = tempfile.TemporaryDirectory(prefix="hwpx-action-inspect-")
    src = Path(temp.name) / "input.hwpx"
    download_action_hwpx(ref, src)
    errors = validate_hwpx(str(src))
    if errors:
        temp.cleanup()
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    result = collect_slots(
        src,
        preview_len=preview_len,
        include_empty_cells=include_empty_cells,
    )
    return ref, result.get("slots", []), temp


@app.post(
    "/action/inspect-summary",
    operation_id="inspectHwpxSummary",
    dependencies=[Depends(require_api_key)],
)
def action_inspect_hwpx_summary(payload: ActionInspectSummaryRequest) -> dict:
    ref, slots, temp = _load_slots(
        payload.openaiFileIdRefs,
        payload.include_empty_cells,
        payload.preview_len,
    )
    try:
        paragraph_count = sum(1 for slot in slots if slot.get("kind") == "paragraph")
        cell_count = sum(1 for slot in slots if slot.get("kind") == "cell")
        return {
            "ok": True,
            "source": ref.name,
            "total_slots": len(slots),
            "paragraph_slots": paragraph_count,
            "cell_slots": cell_count,
            "sample_slots": [_compact_slot(slot) for slot in slots[:3]],
            "next_step": "Use findHwpxText with a phrase from the user's requested edit to locate exact slot keys.",
        }
    finally:
        temp.cleanup()


@app.post(
    "/action/find",
    operation_id="findHwpxText",
    dependencies=[Depends(require_api_key)],
)
def action_find_hwpx_text(payload: ActionFindRequest) -> dict:
    ref, slots, temp = _load_slots(
        payload.openaiFileIdRefs,
        payload.include_empty_cells,
        payload.preview_len,
    )
    try:
        needle = payload.search_text.casefold()
        matches = [
            slot for slot in slots
            if needle in str(slot.get("preview", "")).casefold()
        ]
        shown = matches[: payload.limit]
        return {
            "ok": True,
            "source": ref.name,
            "search_text": payload.search_text,
            "matched_slots": len(matches),
            "returned": len(shown),
            "truncated": len(matches) > len(shown),
            "slots": [_compact_slot(slot) for slot in shown],
        }
    finally:
        temp.cleanup()


@app.post(
    "/action/inspect-page",
    operation_id="inspectHwpxPage",
    dependencies=[Depends(require_api_key)],
)
def action_inspect_hwpx_page(payload: ActionInspectPageRequest) -> dict:
    ref, all_slots, temp = _load_slots(
        payload.openaiFileIdRefs,
        payload.include_empty_cells,
        payload.preview_len,
    )
    try:
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
