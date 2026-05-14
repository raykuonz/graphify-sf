"""Tests for graphify_sf.extract.doc document extractor."""
import tempfile
from pathlib import Path

from graphify_sf.extract.doc import (
    _doc_id,
    _extract_headings,
    extract_doc_file,
    extract_document,
    extract_image,
    extract_paper,
)

SAMPLE_MD = """\
# Introduction

This document describes AccountService and the Account__c object.

## Architecture

The system uses OrderTrigger to process orders.

### Detail

Lower detail here.
"""


def _write_tmp(content: str, suffix: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", encoding="utf-8", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


def test_extract_document_returns_node():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    assert len(result["nodes"]) >= 1
    root_node = result["nodes"][0]
    assert root_node["file_type"] == "document"
    assert root_node["sf_type"] is None
    assert p.name in root_node["label"]


def test_extract_document_headings():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    labels = [n["label"] for n in result["nodes"]]
    assert "Introduction" in labels
    assert "Architecture" in labels
    assert "Detail" in labels


def test_extract_document_heading_edges():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    # All heading nodes should have a contains edge from the root doc node
    doc_id = result["nodes"][0]["id"]
    contains_targets = {e["target"] for e in result["edges"] if e["relation"] == "contains" and e["source"] == doc_id}
    heading_ids = {n["id"] for n in result["nodes"][1:]}
    assert heading_ids.issubset(contains_targets)


def test_extract_document_sf_mentions():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    mention_edges = [e for e in result["edges"] if e.get("_mention_label")]
    mention_labels = {e["_mention_label"] for e in mention_edges}
    # Should detect AccountService, Account__c, OrderTrigger as SF mentions
    assert "AccountService" in mention_labels or len(mention_labels) > 0


def test_extract_image_node_only():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        p = Path(f.name)
    result = extract_image(p)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["file_type"] == "image"
    assert len(result["edges"]) == 0


def test_extract_paper_no_crash_without_pypdf():
    """extract_paper must not crash even if pypdf is not installed."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake")
        p = Path(f.name)
    result = extract_paper(p)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["file_type"] == "paper"


def test_extract_doc_file_dispatch_md():
    p = _write_tmp("# Test", ".md")
    result = extract_doc_file(p)
    assert result["nodes"][0]["file_type"] == "document"


def test_extract_doc_file_dispatch_pdf():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF fake")
        p = Path(f.name)
    result = extract_doc_file(p)
    assert result["nodes"][0]["file_type"] == "paper"


def test_doc_id_stable():
    """Same path must produce the same ID."""
    p = Path("/some/path/README.md")
    assert _doc_id(p) == _doc_id(p)


def test_extract_headings_levels():
    text = "# H1\n## H2\n### H3\n#### H4 (not extracted)\n"
    doc_id = "doc_test"
    nodes, edges = _extract_headings(text, doc_id, "test.md")
    labels = [n["label"] for n in nodes]
    assert "H1" in labels
    assert "H2" in labels
    assert "H3" in labels
    assert "H4 (not extracted)" not in labels
