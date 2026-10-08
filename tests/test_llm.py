"""Tests for ask_agent against a local mock of the Anthropic Messages API.

The mock records each request and streams back a canned reply, so these
tests check the real request shape and response parsing without network
access or an API key.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from swarm.llm import AgentError, ask_agent
from swarm.schemas import BAResponse


class MockAnthropic:
    def __init__(self):
        self.requests: list[dict] = []
        self.reply_text = ""
        self.stop_reason = "end_turn"

    def events(self, model: str):
        yield "message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_test", "type": "message", "role": "assistant", "model": model,
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        }
        # A thinking block first, as adaptive thinking produces.
        yield "content_block_start", {"type": "content_block_start", "index": 0,
                                      "content_block": {"type": "thinking", "thinking": "",
                                                        "signature": ""}}
        yield "content_block_delta", {"type": "content_block_delta", "index": 0,
                                      "delta": {"type": "signature_delta", "signature": "s"}}
        yield "content_block_stop", {"type": "content_block_stop", "index": 0}
        yield "content_block_start", {"type": "content_block_start", "index": 1,
                                      "content_block": {"type": "text", "text": ""}}
        half = len(self.reply_text) // 2
        for chunk in (self.reply_text[:half], self.reply_text[half:]):
            yield "content_block_delta", {"type": "content_block_delta", "index": 1,
                                          "delta": {"type": "text_delta", "text": chunk}}
        yield "content_block_stop", {"type": "content_block_stop", "index": 1}
        yield "message_delta", {"type": "message_delta",
                                "delta": {"stop_reason": self.stop_reason, "stop_sequence": None},
                                "usage": {"output_tokens": 20}}
        yield "message_stop", {"type": "message_stop"}


@pytest.fixture
def mock_api(monkeypatch):
    mock = MockAnthropic()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            mock.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for event, data in mock.events(body["model"]):
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.delenv("SWARM_MODEL", raising=False)
    monkeypatch.delenv("SWARM_EFFORT", raising=False)
    yield mock
    server.shutdown()


QUESTIONS = {"action": "ask_questions", "questions": ["Decimals?"], "requirements": None}


def test_request_shape_and_parsing(mock_api):
    mock_api.reply_text = json.dumps(QUESTIONS)

    result = ask_agent("business_analyst", BAResponse, "Build a converter")

    assert result == BAResponse(**QUESTIONS)
    request = mock_api.requests[0]
    body = request["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["system"].startswith("# Role: Business Analyst")
    assert body["messages"][-1]["content"] == "Build a converter"
    # Native structured outputs, not a forced tool call.
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "high"
    assert "tool_choice" not in body and "tools" not in body
    # Refusal fallbacks are on for this model.
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in request["headers"]["anthropic-beta"]


def test_model_and_effort_come_from_env(mock_api, monkeypatch):
    monkeypatch.setenv("SWARM_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("SWARM_EFFORT", "")
    mock_api.reply_text = json.dumps(QUESTIONS)

    ask_agent("business_analyst", BAResponse, "Build a converter")

    body = mock_api.requests[0]["body"]
    assert body["model"] == "claude-haiku-4-5"
    assert "effort" not in body.get("output_config", {})
    assert "fallbacks" not in body


def test_refusal_raises_agent_error(mock_api):
    mock_api.stop_reason = "refusal"

    with pytest.raises(AgentError, match="declined"):
        ask_agent("business_analyst", BAResponse, "Build a converter")


def test_invalid_output_raises_agent_error(mock_api):
    mock_api.reply_text = json.dumps({"action": "ask_questions"})

    with pytest.raises(AgentError, match="didn't match BAResponse"):
        ask_agent("business_analyst", BAResponse, "Build a converter")
