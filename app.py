from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from finalize_hwpx import find_layout_warnings  # noqa: E402
from hwpx_slots import collect_slots, summarize_slots  # noqa: E402
from page_guard import collect_metrics  # noqa: E402
from validate import validate as validate_hwpx  # noqa: E402

MAX_FILE_BYTES = int(os.getenv("HWPX_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
ACTION_OUTPUT_MAX_FILE_BYTES = 10 * 1024 * 1024
BEARER_SCHEME = HTTPBearer(auto_error=False)

app = FastAPI(
    title="HWPX Skill API",
    version="0.2.0",
    description="Inspect, validate, and edit HWPX files while preserving their original structure.",
)


class ActionFileRef(BaseModel):
    name: str
    id: str | None = None
    mime_type: str | None = None
    download_link: str


class ActionInspectRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    include_empty_cells: bool = True
    preview_len: int = 80


class ActionValidateRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]


class SlotEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_key: str = Field(min_length=3, pattern=r"^(p:\d+|cell:\d+:\d+:\d+(?::\d+)?)$")
    new_text: str


class TextReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_text: str = Field(min_length=1)
    new_text: str


class ParagraphEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraph_index: int = Field(ge=0)
    new_text: str


class ActionEditRequest(BaseModel):
    openaiFileIdRefs: list[ActionFileRef]
    slot_edits: list[SlotEdit] = Field(default_factory=list)
    text_replacements: list[TextReplacement] = Field(default_factory=list)
    paragraph_edits: list[ParagraphEdit] = Field(default_factory=list)
    allow_over_budget: bool = False


class ActionOutputFile(BaseModel):
    name: str
    mime_type: str
    content: str


class ActionEditResponse(BaseModel):
    ok: bool
    validated: bool
    layout_warning_count: int
    openaiFileResponse: list[ActionOutputFile]


class CreateFromTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openaiFileIdRefs: list[ActionFileRef]
    title: str = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1)
    output_filename: str = Field(default="created_from_template.hwpx", min_length=6)


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


def normalize_mapping(value: dict[str, str] | None) -> dict[str, str]:
    return {str(k): "" if v is None else str(v) for k, v in (value or {}).items()}


def action_edit_mappings(payload: ActionEditRequest) -> dict[str, dict[str, str]]:
    return {
        "replacements": {item.old_text: item.new_text for item in payload.text_replacements},
        "slots": {item.slot_key: item.new_text for item in payload.slot_edits},
        "paragraphs": {
            str(item.paragraph_index): item.new_text for item in payload.paragraph_edits
        },
    }


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


def select_action_hwpx(refs: list[ActionFileRef]) -> ActionFileRef:
    if len(refs) != 1:
        raise HTTPException(status_code=400, detail="Provide exactly one HWPX file.")
    ref = refs[0]
    if not ref.name.lower().endswith(".hwpx"):
        raise HTTPException(status_code=400, detail="The referenced file must have a .hwpx filename.")
    return ref


def download_action_hwpx(ref: ActionFileRef, dst: Path) -> None:
    parsed = urllib.parse.urlparse(ref.download_link)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "files.oaiusercontent.com" or host.endswith(".oaiusercontent.com")):
        raise HTTPException(status_code=400, detail="File reference does not contain an allowed OpenAI download URL.")

    request = urllib.request.Request(
        ref.download_link,
        headers={"User-Agent": "hwpxskill-api/0.2.0"},
    )
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=15) as response, dst.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="HWPX file is too large.")
                out.write(chunk)
    except HTTPException:
        dst.unlink(missing_ok=True)
        raise
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        dst.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"Could not download the ChatGPT file reference: {exc}") from exc


def run_edit(
    src: Path,
    out: Path,
    workdir: Path,
    maps: dict[str, dict[str, str]],
    allow_over_budget: bool,
) -> int:
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

    return len(find_layout_warnings(out))


@app.get("/health", operation_id="healthCheck")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hwpxskill-api", "version": "0.2.0"}


# Browser/Swagger endpoints. These keep direct multipart upload support for manual testing.
@app.post("/inspect", operation_id="inspectHwpxMultipart", dependencies=[Depends(require_api_key)])
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


@app.post("/validate", operation_id="validateHwpxMultipart", dependencies=[Depends(require_api_key)])
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
    operation_id="editHwpxMultipart",
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
        warning_count = run_edit(src, out, workdir, maps, allow_over_budget)

        output_name = f"{Path(file.filename or 'document.hwpx').stem}_edited.hwpx"
        background_tasks.add_task(shutil.rmtree, workdir, True)
        return FileResponse(
            out,
            media_type="application/hwp+zip",
            filename=output_name,
            headers={"X-HWPX-Validated": "true", "X-HWPX-Layout-Warnings": str(warning_count)},
            background=background_tasks,
        )
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


# GPT Action endpoints. ChatGPT sends conversation files through openaiFileIdRefs.
@app.post("/action/inspect", operation_id="inspectHwpxLegacy", dependencies=[Depends(require_api_key)])
def action_inspect_hwpx(payload: ActionInspectRequest) -> dict:
    ref = select_action_hwpx(payload.openaiFileIdRefs)
    with tempfile.TemporaryDirectory(prefix="hwpx-action-inspect-") as tmp:
        src = Path(tmp) / "input.hwpx"
        download_action_hwpx(ref, src)
        errors = validate_hwpx(str(src))
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})
        return {
            "ok": True,
            "source": ref.name,
            **summarize_slots(src, include_empty_cells=payload.include_empty_cells),
        }


@app.post("/action/validate", operation_id="validateHwpx", dependencies=[Depends(require_api_key)])
def action_validate_hwpx(payload: ActionValidateRequest) -> dict:
    ref = select_action_hwpx(payload.openaiFileIdRefs)
    with tempfile.TemporaryDirectory(prefix="hwpx-action-validate-") as tmp:
        src = Path(tmp) / "input.hwpx"
        download_action_hwpx(ref, src)
        errors = validate_hwpx(str(src))
        warnings = [] if errors else find_layout_warnings(src)
        return {
            "valid": not errors,
            "errors": errors,
            "layout_warning_count": len(warnings),
            "layout_warnings": warnings[:50],
        }


@app.post(
    "/action/edit",
    operation_id="editHwpx",
    dependencies=[Depends(require_api_key)],
    response_model=ActionEditResponse,
)
def action_edit_hwpx(payload: ActionEditRequest) -> ActionEditResponse:
    ref = select_action_hwpx(payload.openaiFileIdRefs)
    with tempfile.TemporaryDirectory(prefix="hwpx-action-edit-") as tmp:
        workdir = Path(tmp)
        src = workdir / "input.hwpx"
        out = workdir / "edited.hwpx"
        download_action_hwpx(ref, src)

        source_errors = validate_hwpx(str(src))
        if source_errors:
            raise HTTPException(status_code=422, detail={"validation_errors": source_errors})

        maps = action_edit_mappings(payload)
        warning_count = run_edit(src, out, workdir, maps, payload.allow_over_budget)

        output_bytes = out.read_bytes()
        if len(output_bytes) > ACTION_OUTPUT_MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Edited HWPX exceeds the 10 MB GPT Action returned-file limit.",
            )

        output_name = f"{Path(ref.name).stem}_edited.hwpx"
        return ActionEditResponse(**{
            "ok": True,
            "validated": True,
            "layout_warning_count": warning_count,
            "openaiFileResponse": [
                {
                    "name": output_name,
                    "mime_type": "application/hwp+zip",
                    "content": base64.b64encode(output_bytes).decode("ascii"),
                }
            ],
        })


@app.post(
    "/action/create-from-template",
    operation_id="createHwpxFromTemplate",
    dependencies=[Depends(require_api_key)],
    response_model=ActionEditResponse,
)
def action_create_from_template(payload: CreateFromTemplateRequest) -> ActionEditResponse:
    ref = select_action_hwpx(payload.openaiFileIdRefs)
    output_filename = payload.output_filename.strip()
    if Path(output_filename).name != output_filename or not output_filename.lower().endswith(".hwpx"):
        raise HTTPException(status_code=400, detail="output_filename must be a plain .hwpx filename.")

    with tempfile.TemporaryDirectory(prefix="hwpx-action-create-") as tmp:
        workdir = Path(tmp)
        src = workdir / "template.hwpx"
        out = workdir / "created.hwpx"
        download_action_hwpx(ref, src)

        source_errors = validate_hwpx(str(src))
        if source_errors:
            raise HTTPException(status_code=422, detail={"validation_errors": source_errors})

        profile = collect_slots(src, preview_len=20, include_empty_cells=True)
        slots = profile["slots"]
        paragraph_slots = [slot for slot in slots if slot["kind"] == "paragraph"]
        content = [payload.title, *payload.paragraphs]
        if len(paragraph_slots) < len(content):
            raise HTTPException(
                status_code=422,
                detail=f"Template has {len(paragraph_slots)} editable paragraphs but {len(content)} are required.",
            )

        slot_values = {slot["key"]: "" for slot in paragraph_slots}
        for slot, text in zip(paragraph_slots, content):
            slot_values[slot["key"]] = text

        warning_count = run_edit(
            src,
            out,
            workdir,
            {"replacements": {}, "slots": slot_values, "paragraphs": {}},
            allow_over_budget=True,
        )
        output_bytes = out.read_bytes()
        if len(output_bytes) > ACTION_OUTPUT_MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Created HWPX exceeds the 10 MB GPT Action returned-file limit.")

        return ActionEditResponse(
            ok=True,
            validated=True,
            layout_warning_count=warning_count,
            openaiFileResponse=[ActionOutputFile(
                name=output_filename,
                mime_type="application/hwp+zip",
                content=base64.b64encode(output_bytes).decode("ascii"),
            )],
        )

