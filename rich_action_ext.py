from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from fastapi import Depends, HTTPException

import app as app_module
from action_ext import app
from rich_charts import preprocess_chart_fences


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
    response_model=app_module.ActionEditResponse,
)
def action_create_rich_hwpx(
    payload: app_module.CreateRichHwpxRequest,
) -> app_module.ActionEditResponse:
    filename = payload.filename.strip()
    if Path(filename).name != filename or not filename.lower().endswith(".hwpx"):
        raise HTTPException(
            status_code=400,
            detail="filename must be a plain .hwpx filename.",
        )

    with tempfile.TemporaryDirectory(prefix="hwpx-action-rich-") as tmp:
        workdir = Path(tmp)
        markdown_path = workdir / "input.md"
        output = workdir / "output.hwpx"

        try:
            rendered_markdown, png_chart_count = preprocess_chart_fences(
                payload.markdown,
                workdir,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": "PNG chart rendering failed.", "error": str(exc)},
            ) from exc

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
        if proc.returncode != 0 or not output.is_file():
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Kordoc generation failed.",
                    "stderr": proc.stderr[-4000:],
                },
            )

        app_module.add_hancom_compatibility_metadata(output)

        errors = app_module.validate_hwpx(str(output))
        if errors:
            raise HTTPException(
                status_code=500,
                detail={"output_validation_errors": errors},
            )

        output_bytes = output.read_bytes()
        if len(output_bytes) > app_module.ACTION_OUTPUT_MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Created HWPX exceeds the 10 MB GPT Action returned-file limit.",
            )

        return app_module.ActionEditResponse(
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
