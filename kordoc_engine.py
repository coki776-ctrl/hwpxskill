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
    """Generate HWPX through the Kordoc JS API bridge.

    Generated PNG files beside the Markdown input are supplied explicitly to
    Kordoc's ``images`` option so the real image bytes are embedded instead of
    placeholder PNGs.
    """
    bridge = Path(__file__).with_name("kordoc_bridge.mjs")
    image_names = sorted(path.name for path in markdown_path.parent.glob("*.png"))
    command = [
        "node",
        str(bridge),
        str(markdown_path),
        str(output_path),
        preset,
        *image_names,
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
