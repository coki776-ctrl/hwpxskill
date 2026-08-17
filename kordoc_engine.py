from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class KordocResult:
    ok: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def diagnostic(self) -> str:
        return (self.stderr.strip() or self.stdout.strip() or "Kordoc returned no diagnostic text.")[-2500:]


def kordoc_version(timeout: int = 10) -> str:
    proc = subprocess.run(
        ["kordoc", "--version"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "Unable to read Kordoc version")
    return proc.stdout.strip() or proc.stderr.strip()


def generate_hwpx(
    markdown_path: Path,
    output_path: Path,
    *,
    preset: str,
    image_dir: Path | None = None,
    timeout: int = 120,
    extra_args: Sequence[str] = (),
) -> KordocResult:
    """Generate HWPX through Kordoc CLI.

    This module is deliberately thin: FastAPI owns request/response orchestration,
    while Kordoc owns HWPX rendering. Keeping this boundary small prevents the
    server from growing a second document engine.
    """
    command = [
        "kordoc",
        "generate",
        str(markdown_path),
        "-o",
        str(output_path),
        "--preset",
        preset,
    ]
    if image_dir is not None:
        command += ["--image-dir", str(image_dir)]
    command += list(extra_args)

    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return KordocResult(
        ok=proc.returncode == 0 and output_path.is_file(),
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
