from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

from fastapi import Depends
from pydantic import BaseModel, Field

import app as app_module
from action_ext import app
from rich_charts import preprocess_chart_fences


class RichActionResponse(BaseModel):
    ok: bool
    validated: bool
    layout_warning_count: int = 0
    openaiFileResponse: list[app_module.ActionOutputFile] = Field(default_factory=list)
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
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return _failure("kordoc_timeout", "Kordoc generation exceeded 120 seconds.")
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
            output_bytes = output.read_bytes()
        except Exception as exc:
            return _failure("output_read", f"{type(exc).__name__}: {exc}")

        if len(output_bytes) > app_module.ACTION_OUTPUT_MAX_FILE_BYTES:
            return _failure(
                "output_size",
                "Created HWPX exceeds the 10 MB GPT Action returned-file limit.",
            )

        return RichActionResponse(
            ok=True,
            validated=True,
            layout_warning_count=len(app_module.find_layout_warnings(output)),
            openaiFileResponse=[
                app_module.ActionOutputFile(
                    name=filename,
                    mime_type="application/hwp+zip",
                    content=base64.b64encode(output_bytes).decode("ascii"),
                )
            ],
        )
