from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from finalize_hwpx import find_layout_warnings  # noqa: E402
from hwpx_slots import collect_slots  # noqa: E402
from page_guard import collect_metrics  # noqa: E402
from validate import validate as validate_hwpx  # noqa: E402

MAX_FILE_BYTES = int(os.getenv("HWPX_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
BEARER_SCHEME = HTTPBearer(auto_error=False)

app = FastAPI(
    title="HWPX Skill API",
    version="0.1.1",
    description="Inspect, validate, and edit HWPX files while preserving their original structure.",
)


def require_api_key(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(BEARER_SCHEME),
    ] = None,
) -> None:
    expected = os.getenv("HWPX_API_KEY")
    if not expected:
        return
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
    if credentials.credentials != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


async def save_hwpx_upload(upload: UploadFile, dst: Path) -> None:
    if not (upload.filename or "").lower().endswith(".hwpx"):
        raise HTTPException(status_code=400, detail="Only .hwpx files are accepted.")
    size = 0
    try:
        with dst.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="HWPX file is too large.")
                out.write(chunk)
    except Exception:
        dst.unlink(missing_ok=True)
        raise


def parse_mapping(raw: str | None, name: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{name} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{name} must be a JSON object.")
    return {str(k): "" if v is None else str(v) for k, v in value.items()}


def structure_errors(reference: Path, output: Path) -> list[str]:
    ref = collect_metrics(reference)
    out = collect_metrics(output)
    errors: list[str] = []
    if ref.paragraph_count != out.paragraph_count:
        errors.append("paragraph count changed")
    if ref.page_break_count != out.page_break_count:
        errors.append("page break count changed")
    if ref.column_break_count != out.column_break_count:
        errors.append("column break count changed")
    if ref.table_count != out.table_count:
        errors.append("table count changed")
    if ref.table_shapes != out.table_shapes:
        errors.append("table shapes changed")
    return errors


@app.get("/health", operation_id="healthCheck")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hwpxskill-api", "version": "0.1.1"}


@app.post("/inspect", operation_id="inspectHwpx", dependencies=[Depends(require_api_key)])
async def inspect_hwpx(
    file: Annotated[UploadFile, File(description="HWPX file to inspect")],
    include_empty_cells: Annotated[bool, Form()] = True,
    preview_len: Annotated[int, Form()] = 80,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="hwpx-inspect-") as tmp:
        src = Path(tmp) / "input.hwpx"
        await save_hwpx_upload(file, src)
        errors = validate_hwpx(str(src))
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})
        return collect_slots(
            src,
            preview_len=max(10, min(preview_len, 300)),
            include_empty_cells=include_empty_cells,
        )


@app.post("/validate", operation_id="validateHwpx", dependencies=[Depends(require_api_key)])
async def validate_endpoint(
    file: Annotated[UploadFile, File(description="HWPX file to validate")],
) -> dict:
    with tempfile.TemporaryDirectory(prefix="hwpx-validate-") as tmp:
        src = Path(tmp) / "input.hwpx"
        await save_hwpx_upload(file, src)
        errors = validate_hwpx(str(src))
        warnings = [] if errors else find_layout_warnings(src)
        return {
            "valid": not errors,
            "errors": errors,
            "layout_warning_count": len(warnings),
            "layout_warnings": warnings[:50],
        }


@app.post(
    "/edit",
    operation_id="editHwpx",
    dependencies=[Depends(require_api_key)],
    response_class=FileResponse,
)
async def edit_hwpx(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Original HWPX file")],
    replacements: Annotated[str | None, Form(description='JSON object such as {"2024":"2025"}')] = None,
    slots: Annotated[str | None, Form(description='JSON object keyed by p:N or cell:T:R:C')] = None,
    paragraphs: Annotated[str | None, Form(description='JSON object mapping paragraph indices to text')] = None,
    allow_over_budget: Annotated[bool, Form()] = False,
) -> FileResponse:
    workdir = Path(tempfile.mkdtemp(prefix="hwpx-edit-"))
    src = workdir / "input.hwpx"
    out = workdir / "edited.hwpx"
    try:
        await save_hwpx_upload(file, src)
        source_errors = validate_hwpx(str(src))
        if source_errors:
            raise HTTPException(status_code=422, detail={"validation_errors": source_errors})

        maps = {
            "replacements": parse_mapping(replacements, "replacements"),
            "slots": parse_mapping(slots, "slots"),
            "paragraphs": parse_mapping(paragraphs, "paragraphs"),
        }
        if not any(maps.values()):
            raise HTTPException(status_code=400, detail="At least one edit mapping is required.")

        cmd = [sys.executable, str(SCRIPTS / "edit_hwpx.py"), str(src), "--output", str(out)]
        option_names = {
            "replacements": "--replace-json",
            "slots": "--slot-json",
            "paragraphs": "--paragraph-json",
        }
        for name, values in maps.items():
            if values:
                path = workdir / f"{name}.json"
                path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
                cmd += [option_names[name], str(path)]
        if allow_over_budget:
            cmd.append("--allow-over-budget")

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise HTTPException(
                status_code=422,
                detail={"message": "HWPX edit failed.", "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]},
            )

        output_errors = validate_hwpx(str(out))
        if output_errors:
            raise HTTPException(status_code=500, detail={"message": "Output validation failed.", "errors": output_errors})
        drift = structure_errors(src, out)
        if drift:
            raise HTTPException(status_code=500, detail={"message": "Protected structure changed.", "errors": drift})

        warnings = find_layout_warnings(out)
        output_name = f"{Path(file.filename or 'document.hwpx').stem}_edited.hwpx"
        background_tasks.add_task(shutil.rmtree, workdir, True)
        return FileResponse(
            out,
            media_type="application/hwp+zip",
            filename=output_name,
            headers={"X-HWPX-Validated": "true", "X-HWPX-Layout-Warnings": str(len(warnings))},
            background=background_tasks,
        )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
