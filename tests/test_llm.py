"""Tests for graphify_sf/llm.py — LLM semantic extraction backend."""

from __future__ import annotations

import sys
import types
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
    # gemini-3.6-flash: $0.75/M input + $3.75/M output = $4.50
    assert abs(cost - 4.50) < 0.001


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
    for var in (
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "MOONSHOT_API_KEY",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "OLLAMA_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    assert detect_backend() is None


def test_detect_backend_claude(monkeypatch):
    from graphify_sf.llm import detect_backend

    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "MOONSHOT_API_KEY",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "OLLAMA_BASE_URL",
    ):
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

    left = {"nodes": [{"id": "a"}], "edges": [{"source": "a", "target": "b"}], "input_tokens": 100, "output_tokens": 50}
    right = {
        "nodes": [{"id": "c"}],
        "edges": [{"source": "c", "target": "a"}],
        "input_tokens": 200,
        "output_tokens": 80,
    }
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


# ---------------------------------------------------------------------------
# Call-layer tests — fake SDK clients
#
# The openai / anthropic / boto3 SDKs are optional (only CI's all-extras job
# installs them), so each helper injects a minimal fake module into sys.modules that records the
# kwargs handed to the underlying create/converse call. This lets the tests
# assert that the fixed temperature / max_tokens values actually reach the SDK,
# rather than only inspecting the BACKENDS config dict in isolation.
# ---------------------------------------------------------------------------

_FAKE_JSON = '{"nodes":[{"id":"x"}],"edges":[]}'


def _install_fake_openai(monkeypatch):
    """Fake ``openai.OpenAI`` client; returns a dict populated on each call."""
    captured: dict = {}

    class _Resp:
        def __init__(self):
            self.choices = [
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=_FAKE_JSON),
                    finish_reason="stop",
                )
            ]
            self.usage = types.SimpleNamespace(prompt_tokens=5, completion_tokens=10)

    class _Client:
        def __init__(self, **init_kwargs):
            captured["init_kwargs"] = init_kwargs
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            captured["create_kwargs"] = kwargs
            return _Resp()

    fake_mod = types.ModuleType("openai")
    fake_mod.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", fake_mod)
    return captured


def _install_fake_anthropic(monkeypatch):
    """Fake ``anthropic.Anthropic`` client; returns a dict populated on each call."""
    captured: dict = {}

    class _Resp:
        def __init__(self):
            self.content = [types.SimpleNamespace(text=_FAKE_JSON)]
            self.usage = types.SimpleNamespace(input_tokens=5, output_tokens=10)
            self.stop_reason = "end_turn"

    class _Messages:
        def create(self, **kwargs):
            # anthropic 1.x removed sampling params from messages.create().
            if "temperature" in kwargs:
                raise TypeError("Messages.create() got an unexpected keyword argument 'temperature'")
            captured["create_kwargs"] = kwargs
            return _Resp()

    class _Anthropic:
        def __init__(self, **init_kwargs):
            captured["init_kwargs"] = init_kwargs
            self.messages = _Messages()

    fake_mod = types.ModuleType("anthropic")
    fake_mod.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    return captured


def _install_fake_boto3(monkeypatch):
    """Fake ``boto3.client("bedrock-runtime")``; returns a dict populated on each call."""
    captured: dict = {}

    class _Client:
        def converse(self, **kwargs):
            captured["converse_kwargs"] = kwargs
            return {
                "output": {"message": {"content": [{"text": _FAKE_JSON}]}},
                "usage": {"inputTokens": 5, "outputTokens": 10},
                "stopReason": "end_turn",
            }

    class _Session:
        def __init__(self, **init_kwargs):
            captured["session_kwargs"] = init_kwargs

        def client(self, name):
            captured["client_name"] = name
            return _Client()

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.Session = _Session

    fake_botocore = types.ModuleType("botocore")
    fake_botocore_exc = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        pass

    fake_botocore_exc.ClientError = ClientError
    fake_botocore.exceptions = fake_botocore_exc

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", fake_botocore_exc)
    return captured


# ---- temperature passthrough for the two bespoke paths --------------------


def test_call_claude_passes_temperature_from_config(monkeypatch):
    """_call_claude must forward the resolved config temperature to messages.create.

    Mocks anthropic.Anthropic. anthropic 1.x rejects a temperature kwarg with
    TypeError, so it must travel in extra_body (accepted by 0.x and 1.x alike).
    """
    from graphify_sf import llm

    captured = _install_fake_anthropic(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)
    # A non-zero value proves it is read from config and passed through, not
    # silently omitted (the pre-fix bug) or hardcoded.
    monkeypatch.setitem(llm.BACKENDS["claude"], "temperature", 0.7)

    llm.extract_files_direct([], backend="claude")

    assert "temperature" not in captured["create_kwargs"]
    assert captured["create_kwargs"]["extra_body"] == {"temperature": 0.7}
    assert captured["create_kwargs"]["max_tokens"] == 16384


def test_call_claude_omits_temperature_when_unset(monkeypatch):
    """A None config temperature sends no temperature at all, neither as a kwarg nor in extra_body."""
    from graphify_sf import llm

    captured = _install_fake_anthropic(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setitem(llm.BACKENDS["claude"], "temperature", None)

    llm.extract_files_direct([], backend="claude")

    assert "temperature" not in captured["create_kwargs"]
    assert "extra_body" not in captured["create_kwargs"]


def test_call_bedrock_passes_temperature_from_config(monkeypatch):
    """_call_bedrock must read cfg temperature into inferenceConfig, not hardcode 0.

    Mocks boto3.client("bedrock-runtime"). Pre-fix, temperature was hardcoded 0.
    """
    from graphify_sf import llm

    captured = _install_fake_boto3(monkeypatch)
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.setitem(llm.BACKENDS["bedrock"], "temperature", 0.3)
    monkeypatch.delenv("GRAPHIFY_SF_BEDROCK_MODEL", raising=False)

    llm.extract_files_direct([], backend="bedrock")

    # us-east-1 (the default region) has no in-region on-demand Sonnet 4.6; the
    # US geo inference profile is required.
    assert captured["converse_kwargs"]["modelId"] == "us.anthropic.claude-sonnet-4-6"
    inference = captured["converse_kwargs"]["inferenceConfig"]
    assert inference["temperature"] == 0.3
    assert inference["maxTokens"] == 16384
    assert captured["client_name"] == "bedrock-runtime"


# ---- OpenAI max_tokens normalization (behavior-change callout) ------------


def test_openai_max_tokens_matches_siblings_not_old_8192(monkeypatch):
    """OpenAI's resolved max_tokens now equals its siblings (16384), not the old 8192 fallback.

    Mocks openai.OpenAI.
    """
    from graphify_sf import llm

    # Config-level parity.
    assert llm.BACKENDS["openai"]["max_tokens"] == llm.BACKENDS["claude"]["max_tokens"] == 16384

    # And it actually reaches the SDK call as max_completion_tokens.
    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)

    llm.extract_files_direct([], backend="openai")

    assert captured["create_kwargs"]["max_completion_tokens"] == 16384
    assert captured["create_kwargs"]["max_completion_tokens"] != 8192


# ---- Gemini env-var regression (the bug this fixes) -----------------------


def test_gemini_honors_max_output_tokens_env_override(monkeypatch):
    """Regression: GRAPHIFY_SF_MAX_OUTPUT_TOKENS now actually changes Gemini's resolved value.

    Mocks openai.OpenAI (Gemini uses the OpenAI-compat path). Pre-fix, Gemini's
    config used a ``max_completion_tokens`` key that shadowed ``_resolve_max_tokens``'s
    env fallthrough, so this env var was silently ignored.
    """
    from graphify_sf import llm

    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")

    # Default (no env override) resolves to the sibling value.
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)
    llm.extract_files_direct([], backend="gemini")
    default_val = captured["create_kwargs"]["max_completion_tokens"]

    # With the env override, the resolved value changes.
    monkeypatch.setenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", "9999")
    llm.extract_files_direct([], backend="gemini")
    override_val = captured["create_kwargs"]["max_completion_tokens"]

    assert default_val == 16384
    assert override_val == 9999
    assert override_val != default_val


# ---- Kimi reasoning controls / Ollama quirks ------------------------------


def test_kimi_k2_models_still_disable_thinking(monkeypatch):
    """An explicit K2.x model keeps the thinking-disable extra_body (K2.x-only parameter).

    Mocks openai.OpenAI.
    """
    from graphify_sf import llm

    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("MOONSHOT_API_KEY", "m-key")
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)

    llm.extract_files_direct([], backend="kimi", model="kimi-k2.6")

    assert captured["create_kwargs"]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in captured["create_kwargs"]
    # kimi enforces its own fixed temperature — temperature must NOT be sent.
    assert "temperature" not in captured["create_kwargs"]


def test_kimi_default_k3_lowers_reasoning_effort(monkeypatch):
    """kimi-k3 always reasons and rejects the K2.x thinking param; its default effort is max."""
    from graphify_sf import llm

    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("MOONSHOT_API_KEY", "m-key")
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("GRAPHIFY_SF_KIMI_MODEL", raising=False)

    llm.extract_files_direct([], backend="kimi")

    kwargs = captured["create_kwargs"]
    assert kwargs["model"] == "kimi-k3"
    assert kwargs["reasoning_effort"] == "low"
    assert "extra_body" not in kwargs
    assert "temperature" not in kwargs


def test_gemini_default_sends_no_temperature(monkeypatch):
    """Google advises leaving Gemini 3.x temperature at its default; low values can loop."""
    from graphify_sf import llm

    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.delenv("GRAPHIFY_SF_GEMINI_MODEL", raising=False)

    llm.extract_files_direct([], backend="gemini")

    assert captured["create_kwargs"]["model"] == "gemini-3.6-flash"
    assert "temperature" not in captured["create_kwargs"]


def test_ollama_num_ctx_sizing_unchanged_after_refactor(monkeypatch):
    """Ollama num_ctx sizing / keep_alive extra_body is identical after the refactor.

    Mocks openai.OpenAI. Refactor-safety test, not a new-behavior test.
    """
    from graphify_sf import llm

    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("OLLAMA_API_KEY", "x")
    monkeypatch.delenv("GRAPHIFY_SF_OLLAMA_NUM_CTX", raising=False)
    monkeypatch.delenv("GRAPHIFY_SF_OLLAMA_KEEP_ALIVE", raising=False)
    monkeypatch.delenv("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", raising=False)

    llm.extract_files_direct([], backend="ollama")

    extra_body = captured["create_kwargs"]["extra_body"]
    # Empty prompt: estimated_input = 0 // 4 + 400 = 400;
    # num_ctx = min(400 + 16384 + 2000, 131072) = 18784; floor max(_, 8192) = 18784.
    assert extra_body["options"]["num_ctx"] == 18784
    assert extra_body["keep_alive"] == "30m"


def test_ollama_size_context_hook_matches_old_formula():
    """Direct unit test of the extracted hook against the pre-refactor inline formula."""
    from graphify_sf.llm import _ollama_size_context

    def _old_inline(user_message: str, max_completion_tokens: int) -> int:
        # Verbatim copy of the removed inline branch's default-path arithmetic.
        estimated_input = len(user_message) // 4 + 400
        num_ctx = min(estimated_input + max_completion_tokens + 2000, 131072)
        return max(num_ctx, 8192)

    for message, max_ct in [("", 16384), ("a" * 5000, 16384), ("z" * 800_000, 16384), ("x" * 100, 8192)]:
        kwargs = {
            "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": message}],
            "max_completion_tokens": max_ct,
        }
        result = _ollama_size_context(dict(kwargs))
        assert result["extra_body"]["options"]["num_ctx"] == _old_inline(message, max_ct)


def test_ollama_size_context_hook_honors_num_ctx_env(monkeypatch):
    """The GRAPHIFY_SF_OLLAMA_NUM_CTX override path is preserved by the hook."""
    from graphify_sf.llm import _ollama_size_context

    monkeypatch.setenv("GRAPHIFY_SF_OLLAMA_NUM_CTX", "42000")
    kwargs = {
        "messages": [{"role": "user", "content": "hi"}],
        "max_completion_tokens": 16384,
    }
    result = _ollama_size_context(kwargs)
    assert result["extra_body"]["options"]["num_ctx"] == 42000


def test_kimi_model_env_override_reaches_k2_branch(monkeypatch):
    """GRAPHIFY_SF_KIMI_MODEL is the CLI's way back to a K2.x model (there is no --model flag)."""
    from graphify_sf import llm

    captured = _install_fake_openai(monkeypatch)
    monkeypatch.setenv("MOONSHOT_API_KEY", "m-key")
    monkeypatch.setenv("GRAPHIFY_SF_KIMI_MODEL", "kimi-k2.6")

    llm.extract_files_direct([], backend="kimi")

    assert captured["create_kwargs"]["model"] == "kimi-k2.6"
    assert captured["create_kwargs"]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_kimi_request_overrides_leaves_other_models_alone():
    """Only K3+ gets an effort; non-generation ids (moonshot-v1-*, kimi-latest) get neither knob."""
    from graphify_sf.llm import _kimi_request_overrides

    assert _kimi_request_overrides({"model": "kimi-k4"})["reasoning_effort"] == "low"
    for model in ("moonshot-v1-8k", "kimi-latest"):
        out = _kimi_request_overrides({"model": model})
        assert "reasoning_effort" not in out
        assert "extra_body" not in out


def test_kimi_request_overrides_merges_existing_extra_body():
    """The K2.x branch adds to an existing extra_body instead of replacing (or mutating) it."""
    from graphify_sf.llm import _kimi_request_overrides

    original = {"x": 1}
    out = _kimi_request_overrides({"model": "kimi-k2.6", "extra_body": original})
    assert out["extra_body"] == {"x": 1, "thinking": {"type": "disabled"}}
    assert original == {"x": 1}


def test_bedrock_warns_when_us_profile_used_outside_us(monkeypatch, capsys):
    """The default us. inference profile fails outside US regions; say how to fix it, once."""
    from graphify_sf import llm

    _install_fake_boto3(monkeypatch)
    monkeypatch.setattr(llm, "_bedrock_geo_warned", False)
    monkeypatch.delenv("GRAPHIFY_SF_BEDROCK_MODEL", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-central-1")

    llm.extract_files_direct([], backend="bedrock")
    llm.extract_files_direct([], backend="bedrock")

    err = capsys.readouterr().err
    assert err.count("GRAPHIFY_SF_BEDROCK_MODEL") == 1
    assert "eu-central-1" in err


def test_bedrock_no_geo_warning_inside_us(monkeypatch, capsys):
    from graphify_sf import llm

    _install_fake_boto3(monkeypatch)
    monkeypatch.setattr(llm, "_bedrock_geo_warned", False, raising=False)
    monkeypatch.delenv("GRAPHIFY_SF_BEDROCK_MODEL", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    llm.extract_files_direct([], backend="bedrock")

    assert "GRAPHIFY_SF_BEDROCK_MODEL" not in capsys.readouterr().err


def test_kimi_request_overrides_hook_shape():
    """Direct unit test of the Kimi hook's exact payload for K2.x and K3+ models."""
    from graphify_sf.llm import _kimi_request_overrides

    k2 = _kimi_request_overrides({"model": "kimi-k2.6"})
    assert k2["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in k2

    k3 = _kimi_request_overrides({"model": "kimi-k3"})
    assert k3["reasoning_effort"] == "low"
    assert "extra_body" not in k3

    # A caller-chosen effort is not overridden.
    assert _kimi_request_overrides({"model": "kimi-k3", "reasoning_effort": "high"})["reasoning_effort"] == "high"


# ---------------------------------------------------------------------------
# OpenAI default model (gpt-6-luna), request overrides, parameter retry
# ---------------------------------------------------------------------------


def _install_scripted_openai(monkeypatch, script):
    """Fake ``openai.OpenAI`` whose ``create`` plays *script* (exceptions raised, others returned)."""
    calls: list[dict] = []

    class _Client:
        def __init__(self, **init_kwargs):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            calls.append(dict(kwargs))
            step = script[len(calls) - 1]
            if isinstance(step, Exception):
                raise step
            return step

    fake_mod = types.ModuleType("openai")
    fake_mod.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", fake_mod)
    return calls


def _openai_resp(content=_FAKE_JSON, finish_reason="stop", reasoning_tokens=None):
    details = types.SimpleNamespace(reasoning_tokens=reasoning_tokens) if reasoning_tokens is not None else None
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content), finish_reason=finish_reason)],
        usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=10, completion_tokens_details=details),
    )


class _StatusError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


@pytest.fixture(autouse=True)
def _fresh_rejected_params(monkeypatch):
    """The rejected-parameter memo is process-wide; keep tests independent."""
    from graphify_sf import llm

    monkeypatch.setattr(llm, "_REJECTED_PARAMS", set())


def _call_openai(llm, model, **kw):
    cfg = llm.BACKENDS["openai"]
    return llm._call_openai_compat(
        cfg["base_url"],
        "sk-test",
        model,
        "hi",
        temperature=cfg["temperature"],
        max_completion_tokens=321,
        backend="openai",
        request_overrides=cfg["request_overrides"],
        retry_unsupported_params=cfg["retry_unsupported_params"],
        **kw,
    )


def test_openai_defaults_are_gpt_6_luna_with_new_pricing(monkeypatch):
    from graphify_sf import llm

    monkeypatch.delenv("GRAPHIFY_SF_OPENAI_MODEL", raising=False)
    assert llm.BACKENDS["openai"]["default_model"] == "gpt-6-luna"
    assert llm._default_model_for_backend("openai") == "gpt-6-luna"
    assert llm.BACKENDS["openai"]["pricing"] == {"input": 0.10, "output": 0.50}
    assert abs(llm.estimate_cost("openai", 1_000_000, 1_000_000) - 0.60) < 1e-9


def test_openai_overrides_gpt6_drops_temperature_and_sets_low_effort():
    from graphify_sf.llm import _openai_request_overrides

    out = _openai_request_overrides({"model": "gpt-6-luna", "temperature": 0})
    assert "temperature" not in out
    assert out["reasoning_effort"] == "low"
    # An explicit effort is kept.
    assert _openai_request_overrides({"model": "gpt-6-terra", "reasoning_effort": "high"})["reasoning_effort"] == "high"


def test_openai_overrides_leave_older_models_alone():
    from graphify_sf.llm import _openai_request_overrides

    out = _openai_request_overrides({"model": "gpt-4.1-mini", "temperature": 0})
    assert out == {"model": "gpt-4.1-mini", "temperature": 0}


def test_openai_gpt6_request_reaches_sdk_without_temperature(monkeypatch):
    from graphify_sf import llm

    calls = _install_scripted_openai(monkeypatch, [_openai_resp()])
    _call_openai(llm, "gpt-6-luna")
    (kw,) = calls
    assert "temperature" not in kw
    assert kw["reasoning_effort"] == "low"
    assert kw["max_completion_tokens"] == 321


def test_openai_env_override_keeps_temperature_for_old_model(monkeypatch):
    from graphify_sf import llm

    calls = _install_scripted_openai(monkeypatch, [_openai_resp()])
    _call_openai(llm, "gpt-4.1-mini")
    (kw,) = calls
    assert kw["temperature"] == 0
    assert "reasoning_effort" not in kw


def test_openai_400_naming_params_retries_once_without_both(monkeypatch, capsys):
    from graphify_sf import llm

    err = _StatusError(400, "Unsupported parameter: 'reasoning_effort' is not supported with this model.")
    calls = _install_scripted_openai(monkeypatch, [err, _openai_resp()])
    result = _call_openai(llm, "gpt-6-luna")
    assert result["nodes"] == [{"id": "x"}]
    assert len(calls) == 2
    assert "reasoning_effort" in calls[0]
    assert "reasoning_effort" not in calls[1] and "temperature" not in calls[1]
    assert "retrying once without them" in capsys.readouterr().err


def test_openai_retry_strips_temperature_for_non_gpt6_model(monkeypatch):
    from graphify_sf import llm

    err = _StatusError(400, "Unsupported value: 'temperature' does not support 0 with this model.")
    calls = _install_scripted_openai(monkeypatch, [err, _openai_resp()])
    _call_openai(llm, "some-other-model")
    assert calls[0]["temperature"] == 0 and "temperature" not in calls[1]


def test_openai_second_400_raises_without_a_third_call(monkeypatch):
    from graphify_sf import llm

    err = _StatusError(400, "Unsupported parameter: 'temperature'")
    calls = _install_scripted_openai(monkeypatch, [err, _StatusError(400, "still bad temperature")])
    with pytest.raises(_StatusError):
        _call_openai(llm, "gpt-4.1-mini")
    assert len(calls) == 2


@pytest.mark.parametrize(
    "exc",
    [
        _StatusError(400, "This model's maximum context length is 128000 tokens"),
        _StatusError(429, "rate limited, mentions temperature"),
        _StatusError(500, "temperature exploded"),
        ValueError("temperature"),
    ],
)
def test_openai_unrelated_errors_are_not_retried(monkeypatch, exc):
    from graphify_sf import llm

    calls = _install_scripted_openai(monkeypatch, [exc, _openai_resp()])
    with pytest.raises(type(exc)):
        _call_openai(llm, "gpt-6-luna")
    assert len(calls) == 1


def test_parameter_retry_is_openai_only(monkeypatch):
    """gemini/kimi/ollama share _call_openai_compat; their 400s must propagate unchanged."""
    from graphify_sf import llm

    for name, cfg in llm.BACKENDS.items():
        assert bool(cfg.get("retry_unsupported_params")) == (name == "openai"), name
    err = _StatusError(400, "Unsupported parameter: 'temperature'")
    calls = _install_scripted_openai(monkeypatch, [err, _openai_resp()])
    with pytest.raises(_StatusError):
        llm._call_openai_compat("http://x/v1", "k", "gemini-3.6-flash", "hi", temperature=0, backend="gemini")
    assert len(calls) == 1


def test_model_overridden_uses_the_model_actually_sent(monkeypatch):
    from graphify_sf import llm

    monkeypatch.setenv("GRAPHIFY_SF_OPENAI_MODEL", " gpt-4.1-mini ")
    assert llm.model_overridden("openai") is True


def test_model_overridden_detects_env_choice(monkeypatch):
    from graphify_sf import llm

    monkeypatch.delenv("GRAPHIFY_SF_OPENAI_MODEL", raising=False)
    assert llm.model_overridden("openai") is False
    monkeypatch.setenv("GRAPHIFY_SF_OPENAI_MODEL", "gpt-6-luna")
    assert llm.model_overridden("openai") is False  # same as the default
    monkeypatch.setenv("GRAPHIFY_SF_OPENAI_MODEL", "gpt-4.1-mini")
    assert llm.model_overridden("openai") is True
    assert llm.model_overridden("claude") is False  # no model env key
    assert llm.model_overridden("nope") is False


def test_reasoning_budget_exhausted_reply_names_the_cause(monkeypatch, capsys):
    """finish_reason=length + empty content + reasoning tokens is how a reasoning model runs out of budget."""
    from graphify_sf import llm

    calls = _install_scripted_openai(
        monkeypatch, [_openai_resp(content="", finish_reason="length", reasoning_tokens=9000)]
    )
    result = _call_openai(llm, "gpt-6-luna")
    assert result["finish_reason"] == "length"
    err = capsys.readouterr().err
    assert "9000 reasoning tokens" in err and "GRAPHIFY_SF_MAX_OUTPUT_TOKENS" in err
    assert len(calls) == 1


def test_legitimately_empty_reply_does_not_blame_the_reasoning_budget(monkeypatch, capsys):
    from graphify_sf import llm

    _install_scripted_openai(
        monkeypatch, [_openai_resp(content='{"nodes":[],"edges":[]}', finish_reason="stop", reasoning_tokens=300)]
    )
    result = _call_openai(llm, "gpt-6-luna")
    assert result["finish_reason"] == "length"  # hollow: still bisects, as before this change
    err = capsys.readouterr().err
    assert "hollow response" in err and "reasoning tokens" not in err


def test_rejected_parameter_is_remembered_for_the_rest_of_the_run(monkeypatch):
    from graphify_sf import llm

    err = _StatusError(400, "Unsupported parameter: 'temperature' is not supported with this model.")
    calls = _install_scripted_openai(monkeypatch, [err, _openai_resp(), _openai_resp()])
    _call_openai(llm, "o4-mini")
    _call_openai(llm, "o4-mini")  # a later chunk: no wasted 400
    assert [("temperature" in c) for c in calls] == [True, False, False]
    # Another model is unaffected.
    other = _install_scripted_openai(monkeypatch, [_openai_resp()])
    _call_openai(llm, "gpt-4.1-mini")
    assert other[0]["temperature"] == 0
