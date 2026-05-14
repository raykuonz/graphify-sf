"""Tests for doc file detection in graphify_sf.detect."""
import sys
import tempfile
from pathlib import Path

import pytest

from graphify_sf.detect import (
    DocFileType,
    _classify_doc_file,
    detect,
)


def test_classify_md():
    p = Path("README.md")
    assert _classify_doc_file(p) == DocFileType.DOCUMENT


def test_classify_txt():
    assert _classify_doc_file(Path("notes.txt")) == DocFileType.DOCUMENT


def test_classify_pdf():
    assert _classify_doc_file(Path("spec.pdf")) == DocFileType.PAPER


def test_classify_image_png():
    assert _classify_doc_file(Path("diagram.png")) == DocFileType.IMAGE


def test_classify_image_svg():
    assert _classify_doc_file(Path("logo.svg")) == DocFileType.IMAGE


def test_classify_xlsx():
    assert _classify_doc_file(Path("data.xlsx")) == DocFileType.DOCUMENT


def test_classify_docx():
    assert _classify_doc_file(Path("spec.docx")) == DocFileType.DOCUMENT


def test_classify_sf_file_returns_none():
    """SF files must NOT be classified as doc files."""
    assert _classify_doc_file(Path("AccountService.cls")) is None
    assert _classify_doc_file(Path("MyFlow.flow-meta.xml")) is None


def test_detect_returns_doc_files_key(tmp_path):
    """detect() must always return a doc_files key."""
    result = detect(tmp_path)
    assert "doc_files" in result
    assert "document" in result["doc_files"]
    assert "paper" in result["doc_files"]
    assert "image" in result["doc_files"]


def test_detect_finds_markdown(tmp_path):
    (tmp_path / "README.md").write_text("# Hello\nWorld")
    result = detect(tmp_path)
    assert any("README.md" in f for f in result["doc_files"]["document"])


def test_detect_finds_image(tmp_path):
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    result = detect(tmp_path)
    assert any("diagram.png" in f for f in result["doc_files"]["image"])


def test_detect_sf_files_unchanged(tmp_path):
    """Adding doc files must not affect SF file detection."""
    cls_dir = tmp_path / "force-app" / "main" / "default" / "classes"
    cls_dir.mkdir(parents=True)
    (cls_dir / "Foo.cls").write_text("public class Foo {}")
    (tmp_path / "README.md").write_text("# Doc")
    result = detect(tmp_path)
    # SF apex file detected
    assert any("Foo.cls" in f for f in result["files"]["apex"])
    # Doc file detected
    assert any("README.md" in f for f in result["doc_files"]["document"])


def test_detect_skips_graphify_sf_out(tmp_path):
    """Files inside graphify-sf-out/ must be skipped."""
    out_dir = tmp_path / "graphify-sf-out"
    out_dir.mkdir()
    (out_dir / "some-doc.md").write_text("# internal")
    result = detect(tmp_path)
    doc_paths = result["doc_files"]["document"]
    assert not any("graphify-sf-out" in f for f in doc_paths)
