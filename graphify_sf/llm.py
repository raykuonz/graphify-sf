# graphify_sf/llm.py
"""LLM-powered semantic extraction backend for graphify-sf.

Adds AI-discovered edges that static XML/source parsing misses:
  - Business rule duplication (same validation in Apex + Flow)
  - Semantic equivalence between Profiles/PermSets
  - Implicit data couplings not visible in metadata XML
  - Dead metadata: components referenced nowhere in the static graph

Supports 6 backends: Claude, Kimi K2, Gemini, OpenAI, AWS Bedrock, Ollama.

Usage:
    graphify-sf /path/to/sfdx --backend claude
    graphify-sf /path/to/sfdx --backend gemini --token-budget 40000

Environment variables for API keys:
    ANTHROPIC_API_KEY   — claude
    MOONSHOT_API_KEY    — kimi
    GEMINI_API_KEY or GOOGLE_API_KEY — gemini
    OPENAI_API_KEY      — openai
    AWS_PROFILE / AWS_REGION — bedrock
    OLLAMA_BASE_URL     — ollama (local model)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Truncate each file at this many characters when building the user message.
_FILE_CHAR_CAP = 20_000
# Approximate overhead per file for the "=== rel ===" separator line.
_PER_FILE_OVERHEAD_CHARS = 80
# Coarse chars-per-token fallback when tiktoken is not installed.
_CHARS_PER_TOKEN = 4

# Hard cap on LLM response size before json.loads (prevents memory exhaustion).
_LLM_JSON_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Backend registry
# ---------------------------------------------------------------------------

BACKENDS: dict[str, dict] = {
    "claude": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "pricing": {"input": 3.0, "output": 15.0},  # USD per 1M tokens
        "temperature": 0,
        "max_tokens": 16384,
    },
    "kimi": {
        "base_url": "https://api.moonshot.ai/v1",
        "default_model": "kimi-k2-0711-preview",
        "env_key": "MOONSHOT_API_KEY",
        "pricing": {"input": 0.74, "output": 4.66},
        "temperature": None,  # kimi enforces its own fixed temperature
        "max_tokens": 16384,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "env_keys": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "model_env_key": "GRAPHIFY_SF_GEMINI_MODEL",
        "pricing": {"input": 0.10, "output": 0.40},
        "temperature": 0,
        "max_completion_tokens": 16384,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4.1-mini",
        "env_key": "OPENAI_API_KEY",
        "model_env_key": "GRAPHIFY_SF_OPENAI_MODEL",
        "pricing": {"input": 0.40, "output": 1.60},
        "temperature": 0,
    },
    "bedrock": {
        "default_model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "model_env_key": "GRAPHIFY_SF_BEDROCK_MODEL",
        "pricing": {"input": 3.0, "output": 15.0},
        "temperature": 0,
        "max_tokens": 16384,
    },
    "ollama": {
        "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "default_model": os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
        "env_key": "OLLAMA_API_KEY",
        "pricing": {"input": 0.0, "output": 0.0},
        "temperature": 0,
        "max_tokens": 16384,
    },
}


# ---------------------------------------------------------------------------
# Salesforce-specific extraction system prompt
# ---------------------------------------------------------------------------

_SF_EXTRACTION_SYSTEM = """\
You are a Salesforce metadata semantic extraction agent. Extract a knowledge graph fragment \
from the Salesforce SFDX metadata files provided.

Output ONLY valid JSON — no explanation, no markdown fences, no preamble.

You must detect relationships that STATIC XML PARSING CANNOT FIND:
1. Business rule duplication — the same validation logic implemented in BOTH an Apex class \
AND a Flow (e.g., both enforce the same field requirement). Flag as semantically_duplicates.
2. Dead metadata — a Profile/PermissionSet grants access to an Apex class that is never \
called by any Trigger or Flow. Flag the class as potentially_unreferenced.
3. Semantic equivalence — two Profiles or PermissionSets that grant identical or nearly \
identical object/field access. Flag as semantically_equivalent.
4. Implicit data couplings — an Apex class that writes to Object A and a Flow that reads \
from Object A, without any explicit XML edge between them. Flag as shares_data_with.
5. Trigger-bypass risk — DML operations in Apex classes that update objects without \
invoking their associated triggers (e.g., Database.insert with allOrNone=false in a bulk \
utility class used outside trigger context).

Rules:
- EXTRACTED: relationship explicit in source (import, call, XML reference, SOQL/DML target)
- INFERRED: reasonable inference from source patterns (class name conventions, field usage)
- AMBIGUOUS: uncertain — flag for review, do not omit

Node ID format: lowercase, only [a-z0-9_], no dots or slashes.
Format: {stem}_{entity} where stem = filename without extension, entity = symbol or metadata name \
(both normalised).

Output exactly this schema:
{"nodes":[{"id":"stem_entity","label":"Human Readable Name",\
"sf_type":"ApexClass|ApexTrigger|Flow|CustomObject|CustomField|LWCBundle|AuraBundle|\
Profile|PermissionSet|ValidationRule|RecordType|Layout|CustomLabel|NamedCredential|\
ExternalService|unknown",\
"file_type":"apex|trigger|flow|object|field|validation_rule|record_type|layout|lwc|aura|\
profile|permission_set|custom_label|named_credential|external_service|unknown",\
"source_file":"relative/path","source_location":null}],\
"edges":[{"source":"node_id","target":"node_id",\
"relation":"calls|implements|references|contains|extends|queries|dml|triggers|\
semantically_duplicates|semantically_equivalent|shares_data_with|potentially_unreferenced",\
"confidence":"EXTRACTED|INFERRED|AMBIGUOUS","confidence_score":1.0,\
"source_file":"relative/path","source_location":null,"weight":1.0}],\
"input_tokens":0,"output_tokens":0}
"""


# ---------------------------------------------------------------------------
# Tokenizer (optional — falls back to chars/4 heuristic)
# ---------------------------------------------------------------------------

def _get_tokenizer():
    """Return a tiktoken encoder, or None if not installed."""
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


_TOKENIZER = _get_tokenizer()


# ---------------------------------------------------------------------------
# Key / model resolution helpers
# ---------------------------------------------------------------------------

def _backend_env_keys(backend: str) -> list[str]:
    cfg = BACKENDS[backend]
    keys = cfg.get("env_keys")
    if keys:
        return list(keys)
    env_key = cfg.get("env_key")
    return [env_key] if env_key else []


def _get_backend_api_key(backend: str) -> str:
    for env_key in _backend_env_keys(backend):
        value = os.environ.get(env_key)
        if value:
            return value
    return ""


def _format_backend_env_keys(backend: str) -> str:
    keys = _backend_env_keys(backend)
    return " or ".join(keys) if keys else "AWS_PROFILE or AWS_REGION"


def _default_model_for_backend(backend: str) -> str:
    cfg = BACKENDS[backend]
    model_env_key = cfg.get("model_env_key")
    if model_env_key:
        model = os.environ.get(model_env_key)
        if model:
            return model
    return cfg["default_model"]


def _resolve_max_tokens(default: int) -> int:
    """Honour GRAPHIFY_SF_MAX_OUTPUT_TOKENS env var override."""
    raw = os.environ.get("GRAPHIFY_SF_MAX_OUTPUT_TOKENS", "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return default


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def _read_files(paths: list[Path], root: Path) -> str:
    """Return file contents formatted for the extraction prompt."""
    parts: list[str] = []
    for p in paths:
        try:
            rel = p.relative_to(root)
        except ValueError:
            rel = p
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        parts.append(f"=== {rel} ===\n{content[:_FILE_CHAR_CAP]}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_llm_json(raw: str) -> dict:
    """Strip optional markdown fences and parse JSON. Returns empty fragment on failure."""
    if len(raw.encode()) > _LLM_JSON_MAX_BYTES:
        print(
            f"[graphify-sf] LLM response exceeds {_LLM_JSON_MAX_BYTES} bytes; "
            "refusing to parse and dropping chunk.",
            file=sys.stderr,
        )
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        print(f"[graphify-sf] LLM returned invalid JSON, skipping chunk: {exc}", file=sys.stderr)
        return {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}


def _response_is_hollow(raw_content: str | None, parsed: dict) -> bool:
    """Detect a successful HTTP response that yielded no usable extraction."""
    if raw_content is None or not raw_content.strip():
        return True
    nodes = parsed.get("nodes")
    edges = parsed.get("edges")
    return not nodes and not edges


# ---------------------------------------------------------------------------
# Ollama URL validation
# ---------------------------------------------------------------------------

def _validate_ollama_base_url(url: str) -> None:
    """Warn if OLLAMA_BASE_URL looks unsafe (non-loopback http)."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
    except Exception:
        print(f"[graphify-sf] WARNING: OLLAMA_BASE_URL={url!r} is not a parseable URL.", file=sys.stderr)
        return
    if parsed.scheme not in ("http", "https"):
        print(
            f"[graphify-sf] WARNING: OLLAMA_BASE_URL has unexpected scheme {parsed.scheme!r}.",
            file=sys.stderr,
        )
        return
    host = (parsed.hostname or "").lower()
    is_loopback = host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")
    if not is_loopback:
        scheme_note = " (UNENCRYPTED)" if parsed.scheme == "http" else ""
        print(
            f"[graphify-sf] WARNING: OLLAMA_BASE_URL points to non-loopback host "
            f"{host!r}{scheme_note}. Your Salesforce source will be sent to that endpoint. "
            "Set OLLAMA_BASE_URL=http://localhost:11434/v1 to keep extraction local.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Backend call implementations
# ---------------------------------------------------------------------------

def _call_openai_compat(
    base_url: str,
    api_key: str,
    model: str,
    user_message: str,
    temperature: float | None = 0,
    reasoning_effort: str | None = None,
    max_completion_tokens: int = 8192,
    *,
    backend: str = "",
) -> dict:
    """Call any OpenAI-compatible API and return parsed JSON."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        pkg_hint = "graphify-sf[kimi]" if backend == "kimi" else "openai"
        raise ImportError(
            "Gemini/Kimi/Ollama/OpenAI-compatible extraction requires the openai package. "
            f"Run: pip install {pkg_hint}"
        ) from exc

    timeout_raw = os.environ.get("GRAPHIFY_SF_API_TIMEOUT", "").strip()
    timeout_s: float = 600.0
    if timeout_raw:
        try:
            v = float(timeout_raw)
            if v > 0:
                timeout_s = v
        except ValueError:
            pass

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SF_EXTRACTION_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        "max_completion_tokens": max_completion_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    # Kimi-k2 is a reasoning model — disable thinking so content isn't empty
    if "moonshot" in base_url:
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    # Ollama: derive num_ctx from actual prompt size to avoid VRAM pressure
    if backend == "ollama":
        num_ctx_raw = os.environ.get("GRAPHIFY_SF_OLLAMA_NUM_CTX", "").strip()
        if num_ctx_raw:
            try:
                num_ctx = int(num_ctx_raw)
            except ValueError:
                num_ctx = 131072
        else:
            estimated_input = len(user_message) // _CHARS_PER_TOKEN + 400
            num_ctx = min(estimated_input + max_completion_tokens + 2000, 131072)
            num_ctx = max(num_ctx, 8192)
        keep_alive = os.environ.get("GRAPHIFY_SF_OLLAMA_KEEP_ALIVE", "30m")
        kwargs["extra_body"] = {"options": {"num_ctx": num_ctx}, "keep_alive": keep_alive}

    resp = client.chat.completions.create(**kwargs)
    raw_content = resp.choices[0].message.content
    result = _parse_llm_json(raw_content or "{}")
    result["input_tokens"] = resp.usage.prompt_tokens if resp.usage else 0
    result["output_tokens"] = resp.usage.completion_tokens if resp.usage else 0
    result["model"] = model
    result["finish_reason"] = resp.choices[0].finish_reason

    if _response_is_hollow(raw_content, result) and result["finish_reason"] != "length":
        print(
            f"[graphify-sf] {backend or 'backend'} returned a hollow response; "
            "treating as truncation so adaptive retry can bisect the chunk.",
            file=sys.stderr,
        )
        result["finish_reason"] = "length"

    if result.get("output_tokens", 0) < 50 and backend == "ollama":
        print(
            "[graphify-sf] warning: ollama returned very few tokens — check VRAM pressure "
            "or try a larger model with OLLAMA_MODEL=qwen2.5-coder:14b",
            file=sys.stderr,
        )
    return result


def _call_claude(api_key: str, model: str, user_message: str, max_tokens: int = 8192) -> dict:
    """Call Anthropic Claude directly (not via OpenAI compat layer)."""
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "Claude extraction requires the anthropic package. "
            "Run: pip install graphify-sf[claude]"
        ) from exc

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_SF_EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    raw_content = resp.content[0].text if resp.content else None
    result = _parse_llm_json(raw_content or "{}")
    result["input_tokens"] = resp.usage.input_tokens if resp.usage else 0
    result["output_tokens"] = resp.usage.output_tokens if resp.usage else 0
    result["model"] = model
    result["finish_reason"] = "length" if resp.stop_reason == "max_tokens" else "stop"
    if _response_is_hollow(raw_content, result) and result["finish_reason"] != "length":
        print(
            "[graphify-sf] claude returned a hollow response; treating as truncation.",
            file=sys.stderr,
        )
        result["finish_reason"] = "length"
    return result


def _call_bedrock(model: str, user_message: str, max_tokens: int = 8192) -> dict:
    """Call AWS Bedrock via boto3 Converse API."""
    try:
        import boto3
        import botocore.exceptions
    except ImportError as exc:
        raise ImportError(
            "AWS Bedrock extraction requires boto3. Run: pip install graphify-sf[bedrock]"
        ) from exc

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client("bedrock-runtime")

    try:
        resp = client.converse(
            modelId=model,
            system=[{"text": _SF_EXTRACTION_SYSTEM}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
        )
    except botocore.exceptions.ClientError as exc:
        code = exc.response["Error"]["Code"]
        msg = exc.response["Error"]["Message"]
        raise RuntimeError(f"Bedrock API error ({code}): {msg}") from exc

    text = resp.get("output", {}).get("message", {}).get("content", [{}])[0].get("text", "{}")
    result = _parse_llm_json(text)
    usage = resp.get("usage", {})
    result["input_tokens"] = usage.get("inputTokens", 0)
    result["output_tokens"] = usage.get("outputTokens", 0)
    result["model"] = model
    result["finish_reason"] = "length" if resp.get("stopReason") == "max_tokens" else "stop"
    if _response_is_hollow(text, result) and result["finish_reason"] != "length":
        print(
            "[graphify-sf] bedrock returned a hollow response; treating as truncation.",
            file=sys.stderr,
        )
        result["finish_reason"] = "length"
    return result


# ---------------------------------------------------------------------------
# Public single-chunk extraction
# ---------------------------------------------------------------------------

def extract_files_direct(
    files: list[Path],
    backend: str = "claude",
    api_key: str | None = None,
    model: str | None = None,
    root: Path = Path("."),
) -> dict:
    """Extract semantic nodes/edges from a list of Salesforce files using the given backend.

    Returns dict with nodes, edges, input_tokens, output_tokens.
    Raises ValueError for unknown backends.
    Raises ImportError if the required SDK package is missing.
    """
    if backend not in BACKENDS:
        raise ValueError(f"Unknown backend {backend!r}. Available: {sorted(BACKENDS)}")

    cfg = BACKENDS[backend]
    key = api_key or _get_backend_api_key(backend)
    if not key and backend == "ollama":
        ollama_url = os.environ.get("OLLAMA_BASE_URL", cfg.get("base_url", ""))
        _validate_ollama_base_url(ollama_url)
        print(
            "[graphify-sf] WARNING: ollama backend selected with no OLLAMA_API_KEY set; "
            f"sending Salesforce source to {ollama_url}. Set OLLAMA_API_KEY (any non-empty "
            "value) to suppress this warning.",
            file=sys.stderr,
        )
        key = "ollama"
    if not key and backend != "bedrock":
        raise ValueError(
            f"No API key for backend '{backend}'. "
            f"Set {_format_backend_env_keys(backend)} or pass api_key=."
        )

    mdl = model or _default_model_for_backend(backend)
    user_msg = _read_files(files, root)
    max_out = _resolve_max_tokens(cfg.get("max_tokens", 8192))

    if backend == "claude":
        return _call_claude(key, mdl, user_msg, max_tokens=max_out)
    if backend == "bedrock":
        return _call_bedrock(mdl, user_msg, max_tokens=max_out)
    return _call_openai_compat(
        cfg["base_url"],
        key,
        mdl,
        user_msg,
        temperature=cfg.get("temperature", 0),
        reasoning_effort=cfg.get("reasoning_effort"),
        max_completion_tokens=cfg.get("max_completion_tokens", max_out),
        backend=backend,
    )


# ---------------------------------------------------------------------------
# Token estimation + chunk packing
# ---------------------------------------------------------------------------

def _estimate_file_tokens(path: Path) -> int:
    """Estimate the prompt-token cost of a single file."""
    if _TOKENIZER is None:
        try:
            size = path.stat().st_size
        except OSError:
            return 0
        chars = min(size, _FILE_CHAR_CAP) + _PER_FILE_OVERHEAD_CHARS
        return chars // _CHARS_PER_TOKEN
    try:
        content = path.read_text(encoding="utf-8", errors="replace")[:_FILE_CHAR_CAP]
    except OSError:
        return 0
    return len(_TOKENIZER.encode(content)) + (_PER_FILE_OVERHEAD_CHARS // _CHARS_PER_TOKEN)


def _pack_chunks_by_tokens(
    files: list[Path],
    token_budget: int,
) -> list[list[Path]]:
    """Greedily pack files into chunks that fit a token budget.

    Groups files by parent directory first so related metadata artifacts
    (e.g. all fields under the same object directory) share a chunk, which
    improves cross-file edge extraction quality.
    """
    if token_budget <= 0:
        raise ValueError(f"token_budget must be positive, got {token_budget}")

    by_dir: dict[Path, list[Path]] = {}
    for f in files:
        by_dir.setdefault(f.parent, []).append(f)

    chunks: list[list[Path]] = []
    current: list[Path] = []
    current_tokens = 0

    for directory in sorted(by_dir):
        for path in by_dir[directory]:
            cost = _estimate_file_tokens(path)
            if current and current_tokens + cost > token_budget:
                chunks.append(current)
                current = []
                current_tokens = 0
            current.append(path)
            current_tokens += cost

    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# Context-exceeded detection
# ---------------------------------------------------------------------------

_CONTEXT_EXCEEDED_MARKERS = (
    "context size", "context length", "context_length", "context window",
    "exceeds the available", "n_ctx", "maximum context",
    "too many tokens", "prompt is too long", "context_length_exceeded",
)


def _looks_like_context_exceeded(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _CONTEXT_EXCEEDED_MARKERS)


_RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "quota exceeded",
    "quota_exceeded",
    "too many requests",
)
# Max retries on 429 before giving up on a chunk
_RATE_LIMIT_MAX_RETRIES = 5
# Base backoff in seconds (doubles on each attempt: 10, 20, 40, 80, 120)
_RATE_LIMIT_BASE_BACKOFF = 10.0


def _looks_like_rate_limited(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)


def _parse_retry_after(exc: BaseException) -> float | None:
    """Extract the suggested wait time (seconds) from a rate-limit error, or None."""
    msg = str(exc)
    # Gemini: "Please retry in 11.091001825s."
    m = re.search(r"retry in\s+([\d.]+)\s*s", msg, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # Gemini proto: "retryDelay: '11s'"
    m = re.search(r"retryDelay['\"\s:]+(\d+)s", msg, re.IGNORECASE)
    if m:
        return float(m.group(1))
    # Generic Retry-After header value (integer seconds)
    m = re.search(r"retry.after['\"\s:]+(\d+)", msg, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Adaptive retry with bisection
# ---------------------------------------------------------------------------

def _extract_with_adaptive_retry(
    chunk: list[Path],
    backend: str,
    api_key: str | None,
    model: str | None,
    root: Path,
    max_depth: int,
    _depth: int = 0,
) -> dict:
    """Extract a chunk; on truncation or context overflow, bisect and recurse.

    Three signals trigger a retry:
    - ``finish_reason == "length"`` — output truncated at max_completion_tokens
    - Context-window-exceeded API errors (HTTP 400 from various backends)
    - Hollow 200 OK responses (relabelled as "length" by the call functions)

    Recursion is capped at ``max_depth`` (default 3 → up to 8x chunk expansion).
    """
    _EMPTY = {
        "nodes": [], "edges": [],
        "input_tokens": 0, "output_tokens": 0,
        "model": model, "finish_reason": "stop",
    }

    # ── rate-limit-aware call (retries on 429, raises on other errors) ────
    result: dict | None = None
    context_exc: Exception | None = None

    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            result = extract_files_direct(
                chunk, backend=backend, api_key=api_key, model=model, root=root
            )
            break  # success
        except Exception as exc:  # noqa: BLE001
            if _looks_like_rate_limited(exc):
                if attempt < _RATE_LIMIT_MAX_RETRIES:
                    suggested = _parse_retry_after(exc)
                    wait = suggested if suggested else min(
                        _RATE_LIMIT_BASE_BACKOFF * (2 ** attempt), 120.0
                    )
                    print(
                        f"[graphify-sf] rate limited (attempt {attempt + 1}/"
                        f"{_RATE_LIMIT_MAX_RETRIES + 1}), "
                        f"waiting {wait:.0f}s before retry...",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                raise  # exhausted all rate-limit retries
            if _looks_like_context_exceeded(exc):
                context_exc = exc
                break  # handle bisection below
            raise  # other errors propagate immediately

    # ── context window overflow: bisect and recurse ───────────────────────
    if context_exc is not None:
        if len(chunk) <= 1:
            print(
                f"[graphify-sf] single-file chunk {chunk[0]} exceeds model context "
                f"and cannot be split further: {context_exc}",
                file=sys.stderr,
            )
            return _EMPTY
        if _depth >= max_depth:
            print(
                f"[graphify-sf] chunk of {len(chunk)} still overflows context at "
                f"depth {_depth} (max {max_depth}) — dropping",
                file=sys.stderr,
            )
            return _EMPTY
        print(
            f"[graphify-sf] chunk of {len(chunk)} exceeded context at depth {_depth} "
            f"({type(context_exc).__name__}); splitting in half and retrying",
            file=sys.stderr,
        )
        mid = len(chunk) // 2
        left = _extract_with_adaptive_retry(chunk[:mid], backend, api_key, model, root, max_depth, _depth + 1)
        right = _extract_with_adaptive_retry(chunk[mid:], backend, api_key, model, root, max_depth, _depth + 1)
        return _merge_results(left, right, model)

    # ── truncation check ──────────────────────────────────────────────────
    assert result is not None
    if result.get("finish_reason") != "length":
        return result

    if len(chunk) <= 1:
        print(
            f"[graphify-sf] single-file chunk {chunk[0]} truncated at "
            f"max_completion_tokens — partial result kept",
            file=sys.stderr,
        )
        return result

    if _depth >= max_depth:
        print(
            f"[graphify-sf] chunk of {len(chunk)} still truncated at depth {_depth} "
            f"(max {max_depth}) — partial result kept",
            file=sys.stderr,
        )
        return result

    print(
        f"[graphify-sf] chunk of {len(chunk)} truncated at depth {_depth}, "
        f"splitting into halves of {len(chunk) // 2} and {len(chunk) - len(chunk) // 2}",
        file=sys.stderr,
    )
    mid = len(chunk) // 2
    left = _extract_with_adaptive_retry(chunk[:mid], backend, api_key, model, root, max_depth, _depth + 1)
    right = _extract_with_adaptive_retry(chunk[mid:], backend, api_key, model, root, max_depth, _depth + 1)
    return _merge_results(left, right, result.get("model", model))


def _merge_results(left: dict, right: dict, model: str | None) -> dict:
    return {
        "nodes": left.get("nodes", []) + right.get("nodes", []),
        "edges": left.get("edges", []) + right.get("edges", []),
        "input_tokens": left.get("input_tokens", 0) + right.get("input_tokens", 0),
        "output_tokens": left.get("output_tokens", 0) + right.get("output_tokens", 0),
        "model": model,
        "finish_reason": "stop",
    }


# ---------------------------------------------------------------------------
# Parallel corpus extraction
# ---------------------------------------------------------------------------

def extract_corpus_parallel(
    files: list[Path],
    backend: str = "claude",
    api_key: str | None = None,
    model: str | None = None,
    root: Path = Path("."),
    on_chunk_done: Callable | None = None,
    token_budget: int | None = 40_000,
    max_concurrency: int = 4,
    max_retry_depth: int = 3,
) -> dict:
    """Extract a Salesforce corpus in token-budget chunks, merging results.

    Chunking strategy: files are packed by parent directory to maximise
    cross-file edge discovery. Chunks that overflow the model's context
    window are bisected recursively (up to ``max_retry_depth`` levels).

    Ollama is forced to single-worker mode to avoid VRAM pressure; set
    GRAPHIFY_SF_OLLAMA_PARALLEL=1 to override.

    Args:
        files: List of Salesforce metadata file paths to extract.
        backend: LLM backend name (``"claude"``, ``"gemini"``, etc.).
        api_key: Override for the backend API key (reads env var if None).
        model: Override model name (reads env var / default if None).
        root: Project root for relative path display.
        on_chunk_done: Callback ``(idx, total, chunk_result)`` called per chunk.
        token_budget: Max tokens per chunk (default 40_000). Set None to
            disable token-based packing and use single-chunk mode.
        max_concurrency: Thread pool size (default 4).
        max_retry_depth: Max bisection depth on truncation (default 3).

    Returns:
        Merged dict with ``nodes``, ``edges``, ``input_tokens``, ``output_tokens``.
    """
    if token_budget is not None:
        chunks = _pack_chunks_by_tokens(files, token_budget=token_budget)
    else:
        chunks = [files]  # single chunk — no budget splitting

    merged: dict = {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    total = len(chunks)

    def _run_one(idx: int, chunk: list[Path]) -> tuple[int, dict | None, Exception | None]:
        t0 = time.time()
        try:
            result = _extract_with_adaptive_retry(
                chunk,
                backend=backend,
                api_key=api_key,
                model=model,
                root=root,
                max_depth=max_retry_depth,
            )
            result["elapsed_seconds"] = round(time.time() - t0, 2)
            return idx, result, None
        except Exception as exc:  # noqa: BLE001
            return idx, None, exc

    # Ollama is single-GPU and can't handle concurrent requests well
    effective_concurrency = max_concurrency
    if backend == "ollama" and os.environ.get("GRAPHIFY_SF_OLLAMA_PARALLEL", "").strip() != "1":
        effective_concurrency = 1

    workers = max(1, min(effective_concurrency, total))

    if workers == 1:
        for idx, chunk in enumerate(chunks):
            _, result, exc = _run_one(idx, chunk)
            if exc is not None:
                print(f"[graphify-sf] LLM chunk {idx + 1}/{total} failed: {exc}", file=sys.stderr)
                continue
            assert result is not None
            _merge_into(merged, result)
            if callable(on_chunk_done):
                on_chunk_done(idx, total, result)
        return merged

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, idx, chunk) for idx, chunk in enumerate(chunks)]
        for future in as_completed(futures):
            idx, result, exc = future.result()
            if exc is not None:
                print(f"[graphify-sf] LLM chunk {idx + 1}/{total} failed: {exc}", file=sys.stderr)
                continue
            assert result is not None
            _merge_into(merged, result)
            if callable(on_chunk_done):
                on_chunk_done(idx, total, result)

    return merged


def _merge_into(merged: dict, result: dict) -> None:
    """Append a chunk result into the running merged accumulator."""
    merged["nodes"].extend(result.get("nodes", []))
    merged["edges"].extend(result.get("edges", []))
    merged["input_tokens"] += result.get("input_tokens", 0)
    merged["output_tokens"] += result.get("output_tokens", 0)


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def estimate_cost(backend: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a given token count using published pricing."""
    if backend not in BACKENDS:
        return 0.0
    p = BACKENDS[backend]["pricing"]
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Auto-detect backend from environment
# ---------------------------------------------------------------------------

def detect_backend() -> str | None:
    """Return the name of whichever backend has an API key set, or None.

    Priority: gemini → kimi → claude → openai → bedrock → ollama.

    Ollama is checked last so a paid API key is never silently shadowed by
    an incidental OLLAMA_BASE_URL in the environment.
    """
    for backend in ("gemini", "kimi", "claude", "openai"):
        if _get_backend_api_key(backend):
            return backend
    if (
        os.environ.get("AWS_PROFILE")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    ):
        return "bedrock"
    ollama_url = os.environ.get("OLLAMA_BASE_URL")
    if ollama_url:
        _validate_ollama_base_url(ollama_url)
        return "ollama"
    return None
