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


class ActionInspectPageRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    include_empty_cells: bool = False
    preview_len: int = Field(default=60, ge=10, le=120)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    search_text: str | None = Field(
        default=None,
        description="Optional case-insensitive text to filter slot previews before pagination.",
    )


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


@app.post(
    "/action/inspect-page",
    operation_id="inspectHwpxPage",
    dependencies=[Depends(require_api_key)],
)
def action_inspect_hwpx_page(payload: ActionInspectPageRequest) -> dict:
    ref = select_action_hwpx(payload.openaiFileIdRefs)
    with tempfile.TemporaryDirectory(prefix="hwpx-action-inspect-page-") as tmp:
        src = Path(tmp) / "input.hwpx"
        download_action_hwpx(ref, src)
        errors = validate_hwpx(str(src))
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})

        result = collect_slots(
            src,
            preview_len=payload.preview_len,
            include_empty_cells=payload.include_empty_cells,
        )
        all_slots = result.get("slots", [])
        total_slots = len(all_slots)

        filtered = all_slots
        query = (payload.search_text or "").strip()
        if query:
            needle = query.casefold()
            filtered = [
                slot
                for slot in all_slots
                if needle in str(slot.get("preview", "")).casefold()
            ]

        matched_slots = len(filtered)
        start = min(payload.offset, matched_slots)
        end = min(start + payload.limit, matched_slots)
        page = [_compact_slot(slot) for slot in filtered[start:end]]

        return {
            "source": ref.name,
            "total_slots": total_slots,
            "matched_slots": matched_slots,
            "offset": start,
            "limit": payload.limit,
            "returned": len(page),
            "has_more": end < matched_slots,
            "next_offset": end if end < matched_slots else None,
            "search_text": query or None,
            "slots": page,
        }
