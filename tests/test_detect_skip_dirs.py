"""Tests that scaffolding directories are excluded from detection."""

from __future__ import annotations

from pathlib import Path


def _make_cls(path: Path, content: str = "public class Stub {}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_skip_dirs_exclude_scaffolding(tmp_path):
    """Real Apex classes are detected; scaffolding samples are not."""
    # Real metadata
    _make_cls(tmp_path / "force-app/main/default/classes/Real.cls")

    # Agentic-tooling scaffolding samples
    _make_cls(tmp_path / ".agents/skills/foo/assets/Sample.cls")
    _make_cls(tmp_path / ".cursor/rules/bar.cls")

    from graphify_sf.detect import detect

    result = detect(tmp_path)
    apex_stems = [Path(f).stem for f in result["files"]["apex"]]

    assert "Real" in apex_stems, "Real.cls under force-app must be detected"
    assert "Sample" not in apex_stems, ".agents/ sample must be excluded"
    assert "bar" not in apex_stems, ".cursor/ sample must be excluded"
