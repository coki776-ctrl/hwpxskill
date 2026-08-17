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
    timeout: int = 120,
    extra_args: Sequence[str] = (),
) -> KordocResult:
    """Generate HWPX through Kordoc CLI.

    Local Markdown images are resolved by Kordoc relative to the Markdown file,
    so callers should place generated PNGs beside ``markdown_path``. Kordoc
    4.4.0 does not support an ``--image-dir`` option.
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
