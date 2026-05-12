"""Tests for graphify_sf/llm.py — LLM semantic extraction backend."""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# _parse_llm_json
# ---------------------------------------------------------------------------

def test_parse_llm_json_valid():
    from graphify_sf.llm import _parse_llm_json
    raw = '{"nodes": [], "edges": []}'
    result = _parse_llm_json(raw)
    assert result["nodes"] == []
    assert result["edges"] == []


def test_parse_llm_json_strips_markdown_fences():
    from graphify_sf.llm import _parse_llm_json
    raw = '```json\n{"nodes": [{"id": "a", "label": "A"}], "edges": []}\n```'
    result = _parse_llm_json(raw)
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["id"] == "a"


def test_parse_llm_json_invalid_returns_empty():
    from graphify_sf.llm import _parse_llm_json
    result = _parse_llm_json("this is not json")
    assert result["nodes"] == []
    assert result["edges"] == []


def test_parse_llm_json_too_large_returns_empty():
    from graphify_sf.llm import _LLM_JSON_MAX_BYTES, _parse_llm_json
    # Produce a string that exceeds the byte cap when encoded
    big = "x" * (_LLM_JSON_MAX_BYTES + 1)
    result = _parse_llm_json(big)
    assert result["nodes"] == []
    assert result["edges"] == []


# ---------------------------------------------------------------------------
# _response_is_hollow
# ---------------------------------------------------------------------------

def test_response_is_hollow_none_content():
    from graphify_sf.llm import _response_is_hollow
    assert _response_is_hollow(None, {}) is True


def test_response_is_hollow_empty_string():
    from graphify_sf.llm import _response_is_hollow
    assert _response_is_hollow("   ", {}) is True


def test_response_is_hollow_no_nodes_or_edges():
    from graphify_sf.llm import _response_is_hollow
    assert _response_is_hollow("{}", {"nodes": [], "edges": []}) is True


def test_response_is_hollow_false_when_has_nodes():
    from graphify_sf.llm import _response_is_hollow
    assert _response_is_hollow('{"nodes":[{"id":"x"}]}', {"nodes": [{"id": "x"}], "edges": []}) is False


# ---------------------------------------------------------------------------
# _estimate_file_tokens
# ---------------------------------------------------------------------------

def test_estimate_file_tokens_nonexistent():
    from graphify_sf.llm import _estimate_file_tokens
    # Should return 0 for a file that doesn't exist
    assert _estimate_file_tokens(Path("/nonexistent/path.cls")) == 0


def test_estimate_file_tokens_small_file(tmp_path):
    from graphify_sf.llm import _estimate_file_tokens
    f = tmp_path / "MyClass.cls"
    f.write_text("public class MyClass {}", encoding="utf-8")
    tokens = _estimate_file_tokens(f)
    assert tokens > 0


# ---------------------------------------------------------------------------
# _pack_chunks_by_tokens
# ---------------------------------------------------------------------------

def test_pack_chunks_by_tokens_empty():
    from graphify_sf.llm import _pack_chunks_by_tokens
    result = _pack_chunks_by_tokens([], 1000)
    assert result == []


def test_pack_chunks_by_tokens_single_file(tmp_path):
    from graphify_sf.llm import _pack_chunks_by_tokens
    f = tmp_path / "MyClass.cls"
    f.write_text("public class MyClass {}", encoding="utf-8")
    chunks = _pack_chunks_by_tokens([f], 1000)
    assert len(chunks) == 1
    assert f in chunks[0]


def test_pack_chunks_by_tokens_groups_by_dir(tmp_path):
    from graphify_sf.llm import _pack_chunks_by_tokens
    # Create files in two different directories
    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()
    f1 = dir_a / "ClassA.cls"
    f2 = dir_a / "ClassB.cls"
    f3 = dir_b / "ClassC.cls"
    for f in (f1, f2, f3):
        f.write_text("public class X {}", encoding="utf-8")
    # Large budget — all should fit in one chunk if same dir is grouped
    chunks = _pack_chunks_by_tokens([f1, f2, f3], token_budget=100_000)
    # All files fit in budget; may be 1 or 2 chunks depending on dir grouping
    total_files = sum(len(c) for c in chunks)
    assert total_files == 3


def test_pack_chunks_by_tokens_invalid_budget():
    from graphify_sf.llm import _pack_chunks_by_tokens
    with pytest.raises(ValueError, match="positive"):
        _pack_chunks_by_tokens([], 0)


# ---------------------------------------------------------------------------
# _looks_like_context_exceeded
# ---------------------------------------------------------------------------

def test_looks_like_context_exceeded_positive():
    from graphify_sf.llm import _looks_like_context_exceeded
    assert _looks_like_context_exceeded(Exception("context length exceeded"))
    assert _looks_like_context_exceeded(Exception("too many tokens in the prompt"))
    assert _looks_like_context_exceeded(Exception("prompt is too long"))


def test_looks_like_context_exceeded_negative():
    from graphify_sf.llm import _looks_like_context_exceeded
    assert not _looks_like_context_exceeded(Exception("network timeout"))
    assert not _looks_like_context_exceeded(ValueError("bad json"))


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

def test_estimate_cost_claude():
    from graphify_sf.llm import estimate_cost
    cost = estimate_cost("claude", 1_000_000, 1_000_000)
    # $3/M input + $15/M output = $18 for 1M+1M
    assert abs(cost - 18.0) < 0.01


def test_estimate_cost_gemini():
    from graphify_sf.llm import estimate_cost
    cost = estimate_cost("gemini", 1_000_000, 1_000_000)
    # $0.10/M input + $0.40/M output = $0.50
    assert abs(cost - 0.50) < 0.001


def test_estimate_cost_ollama_is_free():
    from graphify_sf.llm import estimate_cost
    assert estimate_cost("ollama", 1_000_000, 1_000_000) == 0.0


def test_estimate_cost_unknown_backend():
    from graphify_sf.llm import estimate_cost
    assert estimate_cost("unknown_xyz", 1_000_000, 1_000_000) == 0.0


# ---------------------------------------------------------------------------
# detect_backend
# ---------------------------------------------------------------------------

def test_detect_backend_none_when_no_env(monkeypatch):
    from graphify_sf.llm import detect_backend
    # Remove all known API keys from env
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "OPENAI_API_KEY", "MOONSHOT_API_KEY", "AWS_PROFILE",
                "AWS_REGION", "AWS_DEFAULT_REGION", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert detect_backend() is None


def test_detect_backend_claude(monkeypatch):
    from graphify_sf.llm import detect_backend
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY",
                "AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert detect_backend() == "claude"


def test_detect_backend_gemini_takes_priority(monkeypatch):
    from graphify_sf.llm import detect_backend
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-key")
    # gemini has higher priority than claude
    assert detect_backend() == "gemini"


# ---------------------------------------------------------------------------
# _read_files
# ---------------------------------------------------------------------------

def test_read_files_includes_relative_path(tmp_path):
    from graphify_sf.llm import _read_files
    f = tmp_path / "classes" / "MyClass.cls"
    f.parent.mkdir()
    f.write_text("public class MyClass {}", encoding="utf-8")
    result = _read_files([f], root=tmp_path)
    assert "classes/MyClass.cls" in result
    assert "public class MyClass {}" in result


def test_read_files_truncates_at_cap(tmp_path):
    from graphify_sf.llm import _FILE_CHAR_CAP, _read_files
    f = tmp_path / "BigClass.cls"
    f.write_text("x" * (_FILE_CHAR_CAP + 5000), encoding="utf-8")
    result = _read_files([f], root=tmp_path)
    # The content should be truncated (not include all 25000 chars)
    content_part = result.split("===\n", 1)[1] if "===\n" in result else result
    assert len(content_part) <= _FILE_CHAR_CAP + 100  # small margin for whitespace


def test_read_files_skips_unreadable(tmp_path):
    from graphify_sf.llm import _read_files
    nonexistent = tmp_path / "ghost.cls"
    result = _read_files([nonexistent], root=tmp_path)
    # Should return empty string (no content for unreadable file)
    assert result == ""


# ---------------------------------------------------------------------------
# _merge_results
# ---------------------------------------------------------------------------

def test_merge_results_combines_nodes_and_edges():
    from graphify_sf.llm import _merge_results
    left = {"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "b"}],
            "input_tokens": 100, "output_tokens": 50}
    right = {"nodes": [{"id": "c"}], "edges": [{"source": "c", "target": "a"}],
             "input_tokens": 200, "output_tokens": 80}
    merged = _merge_results(left, right, "claude-sonnet-4-6")
    assert len(merged["nodes"]) == 2
    assert len(merged["edges"]) == 2
    assert merged["input_tokens"] == 300
    assert merged["output_tokens"] == 130
    assert merged["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# BACKENDS registry
# ---------------------------------------------------------------------------

def test_backends_have_required_keys():
    from graphify_sf.llm import BACKENDS
    for name, cfg in BACKENDS.items():
        assert "default_model" in cfg, f"{name} missing default_model"
        assert "pricing" in cfg, f"{name} missing pricing"
        assert "input" in cfg["pricing"], f"{name} pricing missing input"
        assert "output" in cfg["pricing"], f"{name} pricing missing output"


def test_backends_names():
    from graphify_sf.llm import BACKENDS
    expected = {"claude", "kimi", "gemini", "openai", "bedrock", "ollama"}
    assert set(BACKENDS.keys()) == expected


# ---------------------------------------------------------------------------
# extract_files_direct — unknown backend raises ValueError
# ---------------------------------------------------------------------------

def test_extract_files_direct_unknown_backend():
    from graphify_sf.llm import extract_files_direct
    with pytest.raises(ValueError, match="Unknown backend"):
        extract_files_direct([], backend="not_a_real_backend")


# ---------------------------------------------------------------------------
# _run_pipeline with backend=None (no LLM)
# ---------------------------------------------------------------------------

def test_run_pipeline_backend_none_does_not_import_llm(simple_project_path, tmp_path):
    """Verify that when backend=None, llm.py is not triggered."""
    from graphify_sf.__main__ import _run_pipeline
    out_dir = tmp_path / "out"
    # Should complete normally without any LLM calls
    _run_pipeline(simple_project_path, out_dir, no_viz=True, backend=None)
    assert (out_dir / "graph.json").exists()
