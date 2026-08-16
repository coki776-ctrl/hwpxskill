from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import app as app_module
from action_ext import app
from rich_charts import preprocess_chart_fences


RETURN_DIR = Path(tempfile.gettempdir()) / "hwpx-action-return"
JOB_DIR = Path(tempfile.gettempdir()) / "hwpx-rich-jobs"
RETURN_DIR.mkdir(parents=True, exist_ok=True)
JOB_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_BASE_URL = os.getenv(
    "HWPX_PUBLIC_BASE_URL",
    "https://hwpxskill-api.onrender.com",
).rstrip("/")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
JOB_TTL_SECONDS = 3600


class RichActionResponse(BaseModel):
    ok: bool
    validated: bool
    layout_warning_count: int = 0
    openaiFileResponse: list[str] = Field(default_factory=list)
    error_stage: str | None = None
    error_message: str | None = None


class RichJobStartResponse(BaseModel):
    ok: bool
    job_id: str
    status: str
    message: str


class RichJobStatusResponse(BaseModel):
    ok: bool
    job_id: str
    status: str
    validated: bool = False
    layout_warning_count: int = 0
    filename: str | None = None
    download_url: str | None = None
    error_stage: str | None = None
    error_message: str | None = None


def _failure(stage: str, message: str) -> RichActionResponse:
    return RichActionResponse(
        ok=False,
        validated=False,
        layout_warning_count=0,
        openaiFileResponse=[],
        error_stage=stage,
        error_message=(message or "Unknown error")[-2500:],
    )


def _cleanup_return_files(max_age_seconds: int = JOB_TTL_SECONDS) -> None:
    cutoff = time.time() - max_age_seconds
    for directory in (RETURN_DIR, JOB_DIR):
        try:
            for path in directory.iterdir():
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
        except OSError:
            pass


def _cache_return_file(source: Path, filename: str) -> str:
    _cleanup_return_files()
    token = secrets.token_urlsafe(24)
    target = RETURN_DIR / f"{token}.hwpx"
    shutil.copy2(source, target)
    query = urllib.parse.urlencode({"name": filename})
    return f"{PUBLIC_BASE_URL}/action/file/{token}?{query}"


def _resolve_return_file(token: str, name: str) -> tuple[Path, str]:
    if not _TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=404, detail="File not found.")

    path = RETURN_DIR / f"{token}.hwpx"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found or expired.")

    filename = Path(name).name
    if not filename.lower().endswith(".hwpx"):
        filename = "report.hwpx"
    return path, filename


def _job_json_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.json"


def _job_hwpx_path(job_id: str) -> Path:
    return JOB_DIR / f"{job_id}.hwpx"


def _write_job(job_id: str, data: dict) -> None:
    path = _job_json_path(job_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_job(job_id: str) -> dict:
    if not _TOKEN_RE.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    path = _job_json_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Job state is unreadable: {exc}") from exc


def _job_download_url(job_id: str, filename: str) -> str:
    query = urllib.parse.urlencode({"name": filename})
    return f"{PUBLIC_BASE_URL}/action/rich-job-file/{job_id}?{query}"


def _resolve_job_file(job_id: str, name: str) -> tuple[Path, str]:
    state = _read_job(job_id)
    if state.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet.")
    path = _job_hwpx_path(job_id)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Generated file not found or expired.")
    filename = Path(name or state.get("filename") or "report.hwpx").name
    if not filename.lower().endswith(".hwpx"):
        filename = "report.hwpx"
    return path, filename


def _validate_filename(filename: str) -> str | None:
    if Path(filename).name != filename or not filename.lower().endswith(".hwpx"):
        return "filename must be a plain .hwpx filename."
    return None


def _generate_rich_hwpx(
    payload: app_module.CreateRichHwpxRequest,
    final_output: Path,
) -> tuple[bool, str | None, str | None, int]:
    filename_error = _validate_filename(payload.filename.strip())
    if filename_error:
        return False, "filename", filename_error, 0

    with tempfile.TemporaryDirectory(prefix="hwpx-action-rich-") as tmp:
        workdir = Path(tmp)
        markdown_path = workdir / "input.md"
        output = workdir / "output.hwpx"

        try:
            rendered_markdown, png_chart_count = preprocess_chart_fences(
                payload.markdown,
                workdir,
            )
        except Exception as exc:
            return False, "chart_rendering", f"{type(exc).__name__}: {exc}", 0

        try:
            markdown_path.write_text(rendered_markdown, encoding="utf-8")
            command = [
                "kordoc",
                "generate",
                str(markdown_path),
                "-o",
                str(output),
                "--preset",
                payload.preset,
            ]
            if png_chart_count:
                command += ["--image-dir", str(workdir)]

            proc = app_module.subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, "kordoc_timeout", "Kordoc generation exceeded 120 seconds.", 0
        except Exception as exc:
            return False, "kordoc_launch", f"{type(exc).__name__}: {exc}", 0

        if proc.returncode != 0 or not output.is_file():
            diagnostic = proc.stderr.strip() or proc.stdout.strip() or "Kordoc returned no diagnostic text."
            return False, "kordoc_generation", diagnostic[-2500:], 0

        try:
            app_module.add_hancom_compatibility_metadata(output)
        except Exception as exc:
            return False, "hancom_compatibility", f"{type(exc).__name__}: {exc}", 0

        try:
            errors = app_module.validate_hwpx(str(output))
        except Exception as exc:
            return False, "validation_runtime", f"{type(exc).__name__}: {exc}", 0

        if errors:
            return False, "output_validation", "; ".join(str(item) for item in errors)[-2500:], 0

        try:
            output_size = output.stat().st_size
        except Exception as exc:
            return False, "output_read", f"{type(exc).__name__}: {exc}", 0

        if output_size > app_module.ACTION_OUTPUT_MAX_FILE_BYTES:
            return False, "output_size", "Created HWPX exceeds the 10 MB limit.", 0

        try:
            warnings = len(app_module.find_layout_warnings(output))
            shutil.copy2(output, final_output)
        except Exception as exc:
            return False, "output_store", f"{type(exc).__name__}: {exc}", 0

        return True, None, None, warnings


def _run_rich_job(job_id: str, payload_data: dict) -> None:
    filename = str(payload_data.get("filename") or "report.hwpx")
    _write_job(
        job_id,
        {
            "status": "running",
            "filename": filename,
            "updated_at": time.time(),
        },
    )

    try:
        payload = app_module.CreateRichHwpxRequest(**payload_data)
        ok, error_stage, error_message, warnings = _generate_rich_hwpx(
            payload,
            _job_hwpx_path(job_id),
        )
    except Exception as exc:
        ok = False
        error_stage = "job_runtime"
        error_message = f"{type(exc).__name__}: {exc}"
        warnings = 0

    if ok:
        _write_job(
            job_id,
            {
                "status": "completed",
                "filename": filename,
                "validated": True,
                "layout_warning_count": warnings,
                "download_url": _job_download_url(job_id, filename),
                "updated_at": time.time(),
            },
        )
    else:
        _job_hwpx_path(job_id).unlink(missing_ok=True)
        _write_job(
            job_id,
            {
                "status": "failed",
                "filename": filename,
                "validated": False,
                "layout_warning_count": 0,
                "error_stage": error_stage,
                "error_message": (error_message or "Unknown error")[-2500:],
                "updated_at": time.time(),
            },
        )


@app.head("/action/file/{token}", include_in_schema=False)
def action_head_rich_file(token: str, name: str = "report.hwpx") -> Response:
    path, filename = _resolve_return_file(token, name)
    return Response(
        status_code=200,
        headers={
            "Content-Type": "application/hwp+zip",
            "Content-Length": str(path.stat().st_size),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/action/file/{token}", include_in_schema=False)
def action_download_rich_file(token: str, name: str = "report.hwpx") -> FileResponse:
    path, filename = _resolve_return_file(token, name)
    return FileResponse(
        path,
        media_type="application/hwp+zip",
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


@app.head("/action/rich-job-file/{job_id}", include_in_schema=False)
def action_head_rich_job_file(job_id: str, name: str = "report.hwpx") -> Response:
    path, filename = _resolve_job_file(job_id, name)
    return Response(
        status_code=200,
        headers={
            "Content-Type": "application/hwp+zip",
            "Content-Length": str(path.stat().st_size),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/action/rich-job-file/{job_id}", include_in_schema=False)
def action_download_rich_job_file(job_id: str, name: str = "report.hwpx") -> FileResponse:
    path, filename = _resolve_job_file(job_id, name)
    return FileResponse(
        path,
        media_type="application/hwp+zip",
        filename=filename,
        headers={"Cache-Control": "no-store"},
    )


def _remove_original_create_rich_route() -> None:
    """Replace app.py's PoC route only in the deployed wrapper app."""
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/action/create-rich"
            and "POST" in getattr(route, "methods", set())
        )
    ]


_remove_original_create_rich_route()


@app.post(
    "/action/create-rich-job",
    operation_id="startRichHwpxJob",
    dependencies=[Depends(app_module.require_api_key)],
    response_model=RichJobStartResponse,
)
def action_start_rich_hwpx_job(
    payload: app_module.CreateRichHwpxRequest,
    background_tasks: BackgroundTasks,
) -> RichJobStartResponse:
    filename = payload.filename.strip()
    filename_error = _validate_filename(filename)
    if filename_error:
        raise HTTPException(status_code=400, detail=filename_error)

    _cleanup_return_files()
    job_id = secrets.token_urlsafe(24)
    _write_job(
        job_id,
        {
            "status": "pending",
            "filename": filename,
            "updated_at": time.time(),
        },
    )
    background_tasks.add_task(
        _run_rich_job,
        job_id,
        {
            "filename": filename,
            "markdown": payload.markdown,
            "preset": payload.preset,
        },
    )
    return RichJobStartResponse(
        ok=True,
        job_id=job_id,
        status="pending",
        message="Generation started. Call getRichHwpxJob with this job_id until completed or failed.",
    )


@app.get(
    "/action/create-rich-job/{job_id}",
    operation_id="getRichHwpxJob",
    dependencies=[Depends(app_module.require_api_key)],
    response_model=RichJobStatusResponse,
    response_model_exclude_none=True,
)
def action_get_rich_hwpx_job(
    job_id: str,
    wait_seconds: int = Query(default=8, ge=0, le=10),
) -> RichJobStatusResponse:
    deadline = time.time() + wait_seconds
    while True:
        state = _read_job(job_id)
        status = str(state.get("status") or "failed")
        if status in {"completed", "failed"} or time.time() >= deadline:
            break
        time.sleep(0.4)

    return RichJobStatusResponse(
        ok=status != "failed",
        job_id=job_id,
        status=status,
        validated=bool(state.get("validated", False)),
        layout_warning_count=int(state.get("layout_warning_count", 0)),
        filename=state.get("filename"),
        download_url=state.get("download_url"),
        error_stage=state.get("error_stage"),
        error_message=state.get("error_message"),
    )


@app.post(
    "/action/create-rich",
    operation_id="createRichHwpxSync",
    dependencies=[Depends(app_module.require_api_key)],
    response_model=RichActionResponse,
    response_model_exclude_none=True,
)
def action_create_rich_hwpx(
    payload: app_module.CreateRichHwpxRequest,
) -> RichActionResponse:
    """Synchronous compatibility endpoint kept for Swagger/manual diagnostics."""
    filename = payload.filename.strip()
    filename_error = _validate_filename(filename)
    if filename_error:
        return _failure("filename", filename_error)

    with tempfile.TemporaryDirectory(prefix="hwpx-action-sync-") as tmp:
        output = Path(tmp) / "output.hwpx"
        ok, error_stage, error_message, warnings = _generate_rich_hwpx(payload, output)
        if not ok:
            return _failure(error_stage or "generation", error_message or "Unknown error")
        try:
            file_url = _cache_return_file(output, filename)
        except Exception as exc:
            return _failure("file_cache", f"{type(exc).__name__}: {exc}")
        return RichActionResponse(
            ok=True,
            validated=True,
            layout_warning_count=warnings,
            openaiFileResponse=[file_url],
        )
