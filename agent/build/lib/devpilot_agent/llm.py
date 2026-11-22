"""Provider-agnostic LLM client with tool calling.

Messages use one internal (Anthropic-style) format:
  {"role": "user"|"assistant", "content": [ {type: text|tool_use|tool_result, ...} ]}
Each provider adapter converts to its own wire format.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

log = logging.getLogger("devpilot.llm")


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    # provider-specific data that must be echoed back on the next turn
    # (e.g. Gemini 3 thought signatures in extra_content.google.thought_signature)
    extra: dict[str, Any] | None = None


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    def as_assistant_message(self) -> dict:
        content: list[dict] = []
        if self.text:
            content.append({"type": "text", "text": self.text})
        for c in self.tool_calls:
            block = {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
            if c.extra:
                block["extra_content"] = c.extra
            content.append(block)
        return {"role": "assistant", "content": content}


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse: ...


class LLMError(RuntimeError):
    pass


def _post_with_retry(client: httpx.Client, url: str, headers: dict, body: dict, retries: int = 4) -> dict:
    """POST with retries on rate limits (429), overload (5xx) and network errors.

    Honors Retry-After, and logs every wait so slow runs are explainable."""
    last: str = ""
    for attempt in range(1, retries + 1):
        started = time.monotonic()
        try:
            r = client.post(url, headers=headers, json=body)
        except httpx.TransportError as e:
            last = f"{type(e).__name__} after {time.monotonic() - started:.0f}s"
            log.warning("LLM request attempt %d/%d failed: %s", attempt, retries, last)
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue
        elapsed = time.monotonic() - started
        if r.status_code in (429, 500, 502, 503, 529):
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if attempt < retries:
                wait = _retry_after(r) or 2 ** attempt * (5 if r.status_code == 429 else 1)
                log.warning("LLM %s (attempt %d/%d), waiting %.0fs%s", f"HTTP {r.status_code}", attempt, retries, wait,
                            " - rate limited; free tiers allow only a few requests per minute" if r.status_code == 429 else "")
                time.sleep(wait)
                continue
        if r.status_code >= 400:
            raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
        log.info("LLM call ok in %.1fs", elapsed)
        return r.json()
    raise LLMError(f"request failed after {retries} attempts: {last}")


def _retry_after(r: httpx.Response) -> float | None:
    try:
        return min(float(r.headers.get("retry-after", "")), 120.0)
    except ValueError:
        return None


class AnthropicClient:
    def __init__(self, model: str | None = None, api_key: str | None = None, max_tokens: int = 4096):
        self.model = model or os.getenv("DEVPILOT_MODEL") or "claude-sonnet-5-5"
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or ""
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self.max_tokens = max_tokens
        self._http = httpx.Client(timeout=float(os.getenv("DEVPILOT_TIMEOUT", "120")))

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools],
        }
        data = _post_with_retry(
            self._http,
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            body,
        )
        resp = LLMResponse(
            input_tokens=data.get("usage", {}).get("input_tokens", 0),
            output_tokens=data.get("usage", {}).get("output_tokens", 0),
        )
        for block in data.get("content", []):
            if block["type"] == "text":
                resp.text += block["text"]
            elif block["type"] == "tool_use":
                resp.tool_calls.append(ToolCall(block["id"], block["name"], block["input"]))
        return resp


class OpenAIClient:
    """OpenAI Chat Completions format. Also used for Gemini, Ollama and vLLM, which expose
    OpenAI-compatible endpoints."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        key_env: str = "OPENAI_API_KEY",
        base_url: str | None = None,
        default_model: str = "gpt-4.1",
        http: httpx.Client | None = None,
        reasoning_effort: str | None = None,
    ):
        # Lower thinking = much faster agent steps. "" disables the parameter.
        self.reasoning_effort = os.getenv("DEVPILOT_REASONING_EFFORT", reasoning_effort or "") or None
        self.model = model or os.getenv("DEVPILOT_MODEL") or default_model
        self.api_key = api_key or os.environ.get(key_env) or ""
        if not self.api_key:
            raise LLMError(f"{key_env} is not set")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self._http = http or httpx.Client(timeout=float(os.getenv("DEVPILOT_TIMEOUT", "120")))

    @staticmethod
    def _to_openai(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            texts = [b["text"] for b in m["content"] if b["type"] == "text"]
            if m["role"] == "assistant":
                calls = []
                for b in m["content"]:
                    if b["type"] != "tool_use":
                        continue
                    call = {"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                    if b.get("extra_content"):
                        call["extra_content"] = b["extra_content"]
                    calls.append(call)
                msg: dict = {"role": "assistant", "content": "\n".join(texts) or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:
                for b in m["content"]:
                    if b["type"] == "tool_result":
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                if texts:
                    out.append({"role": "user", "content": "\n".join(texts)})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": self._to_openai(system, messages),
            "tools": [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                for t in tools
            ],
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        data = _post_with_retry(
            self._http,
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
            body,
        )
        choice = data["choices"][0]["message"]
        resp = LLMResponse(
            text=choice.get("content") or "",
            input_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            output_tokens=data.get("usage", {}).get("completion_tokens", 0),
        )
        for c in choice.get("tool_calls") or []:
            resp.tool_calls.append(ToolCall(
                c.get("id") or f"call_{len(resp.tool_calls)}",
                c["function"]["name"],
                json.loads(c["function"]["arguments"] or "{}"),
                extra=c.get("extra_content"),
            ))
        return resp


class ScriptedLLM:
    """Deterministic test double: each call returns the next response produced by `script`.

    `script(call_index, messages, tools) -> LLMResponse`. Used in unit tests and by the offline
    `mock` provider so the full pipeline can run without an API key.
    """

    def __init__(self, script: Callable[[int, list[dict], list[ToolSpec]], LLMResponse]):
        self.script = script
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]) -> LLMResponse:
        self.seen_messages.append([dict(m) for m in messages])
        resp = self.script(self.calls, messages, tools)
        self.calls += 1
        return resp


def make_client(provider: str, model: str | None = None) -> LLMClient:
    provider = provider.lower()
    if provider == "anthropic":
        return AnthropicClient(model)
    if provider == "openai":
        return OpenAIClient(model)
    if provider == "gemini":
        return OpenAIClient(
            model,
            key_env="GEMINI_API_KEY",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            default_model="gemini-3.8-flash",
            reasoning_effort="low",
        )
    if provider == "mock":
        from .mock_provider import mock_reviewer

        return mock_reviewer()
    raise ValueError(f"unknown provider: {provider}")
