"""Tests for graphify_sf.extract.doc document extractor."""

import tempfile
from pathlib import Path

from graphify_sf.extract.doc import (
    _doc_id,
    _extract_headings,
    _sf_mention_edges,
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
    assert root_node["sf_type"] == "Document"
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


def test_document_file_node_sf_type():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    file_node = result["nodes"][0]
    assert file_node["sf_type"] == "Document"


def test_heading_node_sf_type():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    heading_nodes = [n for n in result["nodes"] if "heading_level" in n]
    assert len(heading_nodes) > 0
    for node in heading_nodes:
        assert node["sf_type"] == "DocumentSection"


def test_doc_mention_denylist_skips_common_words():
    """Bare common English words are not emitted as mentions, but suffixed
    SF names (e.g. Account__c) always bypass the denylist."""
    text = "This document is a Note. See the Overview for Data. Account__c holds records."
    edges = _sf_mention_edges(text, "doc_x", "x.md")
    labels = {e["_mention_label"] for e in edges}
    # Denylisted bare words must not appear.
    assert "This" not in labels
    assert "Note" not in labels
    assert "Overview" not in labels
    assert "Data" not in labels
    # Suffixed name bypasses the denylist even though "Account" alone could collide.
    assert "Account__c" in labels


def test_doc_mention_suffixed_name_bypasses_denylist():
    """A denylisted bare word carrying an SF suffix is still detected."""
    # "Data" is denylisted, but "Data__c" carries a high-signal suffix.
    text = "The Data__c object stores rows."
    edges = _sf_mention_edges(text, "doc_x", "x.md")
    labels = {e["_mention_label"] for e in edges}
    assert "Data__c" in labels
    assert "Data" not in labels


def test_doc_mention_code_fence_higher_confidence():
    """The same mention text scores higher inside a fenced code block than in
    bare prose."""
    text = "Prose mentions AccountService here.\n\n```\nAccountService svc = new AccountService();\n```\n"
    edges = _sf_mention_edges(text, "doc_x", "x.md")
    # First occurrence is prose; regex dedupes so only the first offset is kept.
    acct = [e for e in edges if e["_mention_label"] == "AccountService"]
    assert len(acct) == 1
    assert acct[0]["confidence_score"] == 0.6

    # When the only occurrence is inside a fence, the score is the code value.
    text2 = "Intro paragraph.\n\n```\nCustomHandler runs.\n```\n"
    edges2 = _sf_mention_edges(text2, "doc_y", "y.md")
    handler = [e for e in edges2 if e["_mention_label"] == "CustomHandler"]
    assert len(handler) == 1
    assert handler[0]["confidence_score"] == 0.75


def test_doc_mention_inline_code_higher_confidence():
    """A mention inside an inline-code span scores higher than bare prose."""
    text = "Call `OrderProcessor` to enqueue.\n"
    edges = _sf_mention_edges(text, "doc_x", "x.md")
    proc = [e for e in edges if e["_mention_label"] == "OrderProcessor"]
    assert len(proc) == 1
    assert proc[0]["confidence_score"] == 0.75


def test_no_node_has_sf_type_none():
    p = _write_tmp(SAMPLE_MD, ".md")
    result = extract_document(p)
    for node in result["nodes"]:
        assert node["sf_type"] is not None, f"Node {node['id']} has sf_type=None"

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        img_path = Path(f.name)
    img_result = extract_image(img_path)
    for node in img_result["nodes"]:
        assert node["sf_type"] is not None, f"Image node {node['id']} has sf_type=None"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake")
        pdf_path = Path(f.name)
    pdf_result = extract_paper(pdf_path)
    for node in pdf_result["nodes"]:
        assert node["sf_type"] is not None, f"PDF node {node['id']} has sf_type=None"
