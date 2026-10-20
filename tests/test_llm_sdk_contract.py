"""Contract tests against the real LLM SDKs (skipped when an SDK is not installed).

tests/test_llm.py swaps each SDK for a fake, which cannot notice when a new SDK
major release changes a signature (anthropic 1.x removing ``temperature`` from
``messages.create()`` slipped through that way). These tests drive the real
client libraries against a local stdlib HTTP server, so a breaking SDK change
fails here. CI runs them in the all-extras job.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

_FAKE_JSON = '{"nodes":[{"id":"x"}],"edges":[]}'


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append({"path": self.path, "body": body})
        data = json.dumps(self.server.reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_api(monkeypatch):
    """Local HTTP server; set ``.reply`` to the JSON to return, read ``.requests``."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.requests = []
    server.reply = {}
    server.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_call_claude_with_real_anthropic_sdk(fake_api, monkeypatch):
    pytest.importorskip("anthropic")
    from graphify_sf import llm

    monkeypatch.setenv("ANTHROPIC_BASE_URL", fake_api.url)
    fake_api.reply = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": _FAKE_JSON}],
        "stop_reason": "max_tokens",
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 10},
    }

    result = llm._call_claude("sk-test", "claude-sonnet-4-6", "hello", max_tokens=123, temperature=0.4)

    assert result["nodes"] == [{"id": "x"}]
    assert (result["input_tokens"], result["output_tokens"]) == (5, 10)
    assert result["finish_reason"] == "length"
    (req,) = fake_api.requests
    assert req["path"] == "/v1/messages"
    assert req["body"]["max_tokens"] == 123
    assert req["body"]["temperature"] == 0.4


@pytest.mark.parametrize(
    ("model", "expect_effort", "expect_thinking"),
    [("kimi-k3", "low", None), ("kimi-k2.6", None, {"type": "disabled"})],
)
def test_call_openai_compat_with_real_openai_sdk(fake_api, model, expect_effort, expect_thinking):
    pytest.importorskip("openai")
    from graphify_sf import llm

    fake_api.reply = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4.1-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _FAKE_JSON},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
    }

    result = llm._call_openai_compat(
        f"{fake_api.url}/v1",
        "sk-test",
        model,
        "hello",
        temperature=0.2,
        max_completion_tokens=321,
        request_overrides=llm._kimi_request_overrides,
    )

    assert result["nodes"] == [{"id": "x"}]
    assert (result["input_tokens"], result["output_tokens"]) == (5, 10)
    assert result["finish_reason"] == "stop"
    (req,) = fake_api.requests
    assert req["path"] == "/v1/chat/completions"
    body = req["body"]
    assert body["max_completion_tokens"] == 321
    assert body["temperature"] == 0.2
    assert body.get("reasoning_effort") == expect_effort
    assert body.get("thinking") == expect_thinking


def test_call_bedrock_with_real_boto3(fake_api, monkeypatch, tmp_path):
    pytest.importorskip("boto3")
    from graphify_sf import llm

    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", fake_api.url)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    # Keep a developer's ~/.aws config (profiles, ignore_configured_endpoint_urls)
    # from redirecting the call to real AWS.
    monkeypatch.setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "false")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws-credentials"))
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    fake_api.reply = {
        "output": {"message": {"role": "assistant", "content": [{"text": _FAKE_JSON}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 5, "outputTokens": 10, "totalTokens": 15},
        "metrics": {"latencyMs": 1},
    }

    result = llm._call_bedrock("test-model", "hello", max_tokens=222, temperature=0.3)

    assert result["nodes"] == [{"id": "x"}]
    assert (result["input_tokens"], result["output_tokens"]) == (5, 10)
    (req,) = fake_api.requests
    assert req["path"] == "/model/test-model/converse"
    assert req["body"]["inferenceConfig"] == {"maxTokens": 222, "temperature": 0.3}
