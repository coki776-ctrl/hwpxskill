from pathlib import Path
from types import SimpleNamespace

import kordoc_engine


def test_generate_hwpx_builds_kordoc_command(monkeypatch, tmp_path: Path):
    md = tmp_path / "input.md"
    out = tmp_path / "output.hwpx"
    images = tmp_path / "images"
    md.write_text("# 테스트", encoding="utf-8")
    images.mkdir()
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        out.write_bytes(b"dummy")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(kordoc_engine.subprocess, "run", fake_run)

    result = kordoc_engine.generate_hwpx(
        md,
        out,
        preset="보고서",
        image_dir=images,
    )

    assert result.ok is True
    assert captured["command"] == [
        "kordoc",
        "generate",
        str(md),
        "-o",
        str(out),
        "--preset",
        "보고서",
        "--image-dir",
        str(images),
    ]


def test_generate_hwpx_reports_cli_failure(monkeypatch, tmp_path: Path):
    md = tmp_path / "input.md"
    out = tmp_path / "output.hwpx"
    md.write_text("# 실패 테스트", encoding="utf-8")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="bad preset")

    monkeypatch.setattr(kordoc_engine.subprocess, "run", fake_run)

    result = kordoc_engine.generate_hwpx(md, out, preset="보고서")

    assert result.ok is False
    assert result.returncode == 2
    assert "bad preset" in result.diagnostic


def test_generate_hwpx_requires_output_file(monkeypatch, tmp_path: Path):
    md = tmp_path / "input.md"
    out = tmp_path / "output.hwpx"
    md.write_text("# 출력 없음", encoding="utf-8")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(kordoc_engine.subprocess, "run", fake_run)

    result = kordoc_engine.generate_hwpx(md, out, preset="보고서")

    assert result.ok is False


def test_kordoc_version_raises_on_failure(monkeypatch):
    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="not installed")

    monkeypatch.setattr(kordoc_engine.subprocess, "run", fake_run)

    try:
        kordoc_engine.kordoc_version()
    except RuntimeError as exc:
        assert "not installed" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")
