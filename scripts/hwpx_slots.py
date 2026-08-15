#!/usr/bin/env python3
"""List editable text slots in a HWPX template.

The output is intended to be filled back with scripts/edit_hwpx.py --slot-json.
It deliberately excludes container paragraphs that only wrap tables, pictures,
or text boxes, because editing them creates overlapping text.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

from lxml import etree

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
}


def _parse_section(path: Path) -> etree._Element:
    with zipfile.ZipFile(path, "r") as zf:
        return etree.parse(BytesIO(zf.read("Contents/section0.xml"))).getroot()


def _node_text(node: etree._Element) -> str:
    return "".join(node.itertext())


def _direct_text(paragraph: etree._Element) -> str:
    return "".join(
        _node_text(t)
        for t in paragraph.xpath("./hp:run/hp:t", namespaces=NS)
    )


def _all_text(scope: etree._Element) -> str:
    return "".join(scope.xpath(".//hp:t//text()", namespaces=NS))


def _normalized_len(text: str) -> int:
    return len("".join(text.split()))


def _preview(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _has_nested_paragraph(paragraph: etree._Element) -> bool:
    return bool(paragraph.xpath(".//hp:p", namespaces=NS))


def _iter_paragraph_slots(root: etree._Element, preview_len: int) -> Iterator[dict[str, Any]]:
    for index, paragraph in enumerate(root.xpath(".//hp:p", namespaces=NS)):
        text = _direct_text(paragraph)
        if not text.strip():
            continue
        if _has_nested_paragraph(paragraph):
            continue
        yield {
                "key": f"p:{index}",
                "kind": "paragraph",
                "index": index,
                "max_chars": _normalized_len(text),
                "text_len": len(text),
                "text_len_nospace": _normalized_len(text),
                "preview": _preview(text, preview_len),
            }


def _iter_cell_slots(
    root: etree._Element,
    preview_len: int,
    include_empty: bool,
) -> Iterator[dict[str, Any]]:
    for table_index, table in enumerate(root.xpath(".//hp:tbl", namespaces=NS)):
        seen: dict[tuple[str, str], int] = {}
        for cell in table.xpath(".//hp:tc", namespaces=NS):
            addr = cell.find("hp:cellAddr", namespaces=NS)
            if addr is None:
                continue
            row = addr.get("rowAddr", "0")
            col = addr.get("colAddr", "0")
            occurrence = seen.get((row, col), 0)
            seen[(row, col)] = occurrence + 1
            text = _all_text(cell)
            if not include_empty and not text.strip():
                continue
            key = f"cell:{table_index}:{row}:{col}"
            if occurrence:
                key += f":{occurrence}"
            yield {
                    "key": key,
                    "kind": "cell",
                    "table": table_index,
                    "row": int(row),
                    "col": int(col),
                    "occurrence": occurrence,
                    "max_chars": _normalized_len(text),
                    "text_len": len(text),
                    "text_len_nospace": _normalized_len(text),
                    "empty": not bool(text.strip()),
                    "preview": _preview(text, preview_len),
                }


def iter_slots(
    path: Path,
    preview_len: int = 80,
    include_empty_cells: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield slots without constructing the complete response-sized slot list."""
    root = _parse_section(path)
    yield from _iter_paragraph_slots(root, preview_len)
    yield from _iter_cell_slots(root, preview_len, include_empty_cells)


def summarize_slots(path: Path, include_empty_cells: bool = False) -> dict[str, int]:
    """Return counts only; previews and a complete slot list are never created."""
    paragraph_count = 0
    cell_count = 0
    for slot in iter_slots(path, preview_len=1, include_empty_cells=include_empty_cells):
        if slot["kind"] == "paragraph":
            paragraph_count += 1
        else:
            cell_count += 1
    return {
        "total_slots": paragraph_count + cell_count,
        "paragraph_slots": paragraph_count,
        "cell_slots": cell_count,
    }


def collect_slots(
    path: Path,
    preview_len: int = 80,
    include_empty_cells: bool = True,
) -> dict[str, Any]:
    slots = list(iter_slots(path, preview_len, include_empty_cells))
    return {
        "source": str(path),
        "version": 1,
        "usage": "Fill with scripts/edit_hwpx.py template.hwpx -o out.hwpx --slot-json values.json",
        "slots": slots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HWPX ?몄쭛 媛???띿뒪???щ’ 異붿텧")
    parser.add_argument("input", type=Path, help="?쒗뵆由?.hwpx")
    parser.add_argument("--output", "-o", type=Path, help="?щ’ JSON ???寃쎈줈")
    parser.add_argument("--preview-len", type=int, default=80)
    parser.add_argument(
        "--no-empty-cells",
        action="store_true",
        help="鍮???? ?щ’??異쒕젰?섏? ?딆쓬",
    )
    parser.add_argument("--pretty", action="store_true", help="???뺥깭 ?붿빟 異쒕젰")
    args = parser.parse_args()

    profile = collect_slots(
        args.input,
        args.preview_len,
        include_empty_cells=not args.no_empty_cells,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"WROTE: {args.output}")
        print(f"  slots: {len(profile['slots'])}")
        return 0

    if args.pretty:
        for slot in profile["slots"]:
            print(
                f"{slot['key']}\t{slot['kind']}\tmax={slot['max_chars']}\t"
                f"empty={slot.get('empty', False)}\t{slot['preview']}"
            )
    else:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

