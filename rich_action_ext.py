from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from fastapi import Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import app as app_module
from action_ext import app
from rich_charts import preprocess_chart_fences


RETURN_DIR = Path(tempfile.gettempdir()) / "hwpx-action-return"
RETURN_DIR.mkdir(parents=True, exist_ok=True)
PUBLIC_BASE_URL = os.getenv(
    "HWPX_PUBLIC_BASE_URL",
    "https://hwpxskill-api.onrender.com",
).rstrip("/")
_RETURN_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,80}$")


class RichActionResponse(BaseModel):
    ok: bool
    validated: bool
    layout_warning_count: int = 0
    openaiFileResponse: list[str] = Field(default_factory=list)
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


def _cleanup_return_files(max_age_seconds: int = 3600) -> None:
    cutoff = time.time() - max_age_seconds
    try:
        for path in RETURN_DIR.glob("*.hwpx"):
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
    if not _RETURN_TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=404, detail="File not found.")

    path = RETURN_DIR / f"{token}.hwpx"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found or expired.")

    filename = Path(name).name
    if not filename.lower().endswith(".hwpx"):
        filename = "report.hwpx"
    return path, filename


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
    "/action/create-rich",
    operation_id="createRichHwpx",
    dependencies=[Depends(app_module.require_api_key)],
    response_model=RichActionResponse,
    response_model_exclude_none=True,
)
def action_create_rich_hwpx(
    payload: app_module.CreateRichHwpxRequest,
) -> RichActionResponse:
    filename = payload.filename.strip()
    if Path(filename).name != filename or not filename.lower().endswith(".hwpx"):
        return _failure("filename", "filename must be a plain .hwpx filename.")

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
            return _failure("chart_rendering", f"{type(exc).__name__}: {exc}")

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
                timeout=40,
            )
        except subprocess.TimeoutExpired:
            return _failure("kordoc_timeout", "Kordoc generation exceeded 40 seconds.")
        except Exception as exc:
            return _failure("kordoc_launch", f"{type(exc).__name__}: {exc}")

        if proc.returncode != 0 or not output.is_file():
            diagnostic = proc.stderr.strip() or proc.stdout.strip() or "Kordoc returned no diagnostic text."
            return _failure("kordoc_generation", diagnostic)

        try:
            app_module.add_hancom_compatibility_metadata(output)
        except Exception as exc:
            return _failure("hancom_compatibility", f"{type(exc).__name__}: {exc}")

        try:
            errors = app_module.validate_hwpx(str(output))
        except Exception as exc:
            return _failure("validation_runtime", f"{type(exc).__name__}: {exc}")

        if errors:
            return _failure("output_validation", "; ".join(str(item) for item in errors))

        try:
            output_size = output.stat().st_size
        except Exception as exc:
            return _failure("output_read", f"{type(exc).__name__}: {exc}")

        if output_size > app_module.ACTION_OUTPUT_MAX_FILE_BYTES:
            return _failure(
                "output_size",
                "Created HWPX exceeds the 10 MB GPT Action returned-file limit.",
            )

        try:
            file_url = _cache_return_file(output, filename)
        except Exception as exc:
            return _failure("file_cache", f"{type(exc).__name__}: {exc}")

        return RichActionResponse(
            ok=True,
            validated=True,
            layout_warning_count=len(app_module.find_layout_warnings(output)),
            openaiFileResponse=[file_url],
        )
