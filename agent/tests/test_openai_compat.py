"""OpenAI-compatible adapter (OpenAI / Gemini / Ollama), tested against a fake HTTP server."""
import json

import httpx

from devpilot_agent.agent import ReviewAgent
from devpilot_agent.llm import OpenAIClient
from devpilot_agent.repo import InMemoryRepo


def _tool_call(call_id, name, args, signature=None):
    call = {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    if signature:
        call["extra_content"] = {"google": {"thought_signature": signature}}
    return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5}}


def test_gemini_thought_signature_round_trip(sample_diff, sample_files):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((str(request.url), request.headers["authorization"], body))
        if len(requests) == 1:
            return httpx.Response(200, json=_tool_call("c1", "read_file", {"path": "src/UserService.java"}, signature="SIG-123"))
        return httpx.Response(200, json=_tool_call("c2", "submit_review", {"summary": "ok", "comments": []}, signature="SIG-456"))

    client = OpenAIClient(
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-3.8-flash",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = ReviewAgent(client).review(InMemoryRepo(sample_diff, sample_files))

    assert result.summary == "ok" and result.steps == 2 and result.input_tokens == 100
    url, auth, first = requests[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert auth == "Bearer test-key" and first["model"] == "gemini-3.8-flash"
    assert first["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in first["tools"]} == {"read_file", "search_code", "submit_review"}

    # The second request must echo the thought signature and carry the tool result.
    second = requests[1][2]["messages"]
    assistant = next(m for m in second if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "SIG-123"}}
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "c1" and "UserService" in tool_msg["content"]


def test_missing_key_is_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        OpenAIClient(key_env="GEMINI_API_KEY")
    except Exception as e:  # noqa: BLE001
        assert "GEMINI_API_KEY is not set" in str(e)
    else:
        raise AssertionError("expected error")
