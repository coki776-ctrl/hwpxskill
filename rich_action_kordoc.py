from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import app as app_module
import rich_action_ext as legacy
from kordoc_engine import generate_hwpx
from rich_charts import preprocess_chart_fences


app = legacy.app


def _generate_rich_hwpx(
    payload: app_module.CreateRichHwpxRequest,
    final_output: Path,
) -> tuple[bool, str | None, str | None, int]:
    """Generate rich HWPX with Kordoc as the single rendering engine.

    The existing FastAPI routes, job handling, download URLs, validation,
    and compatibility post-processing remain in ``rich_action_ext``. Only
    the document-rendering boundary is replaced here so the migration is
    easy to roll back while parity is verified.
    """
    filename_error = legacy._validate_filename(payload.filename.strip())
    if filename_error:
        return False, "filename", filename_error, 0

    with tempfile.TemporaryDirectory(prefix="hwpx-action-kordoc-") as tmp:
        workdir = Path(tmp)
        markdown_path = workdir / "input.md"
        output = workdir / "output.hwpx"

        try:
            rendered_markdown, png_chart_count = preprocess_chart_fences(
                payload.markdown,
                workdir,
            )
            markdown_path.write_text(rendered_markdown, encoding="utf-8")
        except Exception as exc:
            return False, "chart_rendering", f"{type(exc).__name__}: {exc}", 0

        try:
            result = generate_hwpx(
                markdown_path,
                output,
                preset=payload.preset,
                image_dir=workdir if png_chart_count else None,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, "kordoc_timeout", "Kordoc generation exceeded 120 seconds.", 0
        except Exception as exc:
            return False, "kordoc_launch", f"{type(exc).__name__}: {exc}", 0

        if not result.ok:
            return False, "kordoc_generation", result.diagnostic, 0

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


# Existing route handlers in rich_action_ext resolve this global at call time.
# Swapping it here lets us preserve all API behavior while centralizing rendering
# in kordoc_engine.py.
legacy._generate_rich_hwpx = _generate_rich_hwpx
