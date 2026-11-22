"""Offline stand-in for an LLM so the whole pipeline runs without an API key.

THIS IS NOT AN LLM. It drives the same agent loop (search_code -> read_file -> submit_review)
using a handful of regex rules, so you can exercise tool calls, the verifier, the API and the
GitHub integration end to end in CI or on a laptop. Real review quality comes from
`--provider anthropic` or `--provider openai`.
"""
from __future__ import annotations

import re

from .diff_parser import parse_unified_diff
from .llm import LLMResponse, ScriptedLLM, ToolCall

_RULES: list[tuple[re.Pattern, str, str, str, str]] = [
    (
        re.compile(r"""(\w+\s*==\s*"|"[^"]*"\s*==\s*\w)"""),
        "bug", "major",
        "String compared with `==`; in Java this compares references, not contents, so equal strings can fail the check.",
        "Use `\"literal\".equals(value)` or `Objects.equals(a, b)`.",
    ),
    (
        re.compile(r"""(?i)["'](select|insert|update|delete)\b[^"']*["']\s*\+|f["'](select|insert|update|delete)\b.*\{"""),
        "security", "critical",
        "SQL built by string concatenation with runtime values: this is open to SQL injection.",
        "Use a parameterized query (PreparedStatement / bound parameters).",
    ),
    (
        re.compile(r"""^\s*except\s*(Exception)?\s*:\s*(pass)?\s*$"""),
        "error_handling", "major",
        "Broad `except` swallows every error, hiding real failures and making debugging very hard.",
        "Catch the specific exception you expect and log or re-raise the rest.",
    ),
    (
        re.compile(r"""(?i)(password|secret|api_key|apikey|token)\s*[:=]\s*["'][^"']{6,}["']"""),
        "security", "critical",
        "Hard-coded credential committed to source control.",
        "Load it from an environment variable or a secrets manager and rotate the leaked value.",
    ),
    (
        re.compile(r"""catch\s*\(\s*\w+\s+\w+\s*\)\s*\{\s*\}"""),
        "error_handling", "major",
        "Empty catch block silently ignores the exception.",
        "Log the exception with context or rethrow a wrapped exception.",
    ),
]


def _first_user_text(messages: list[dict]) -> str:
    for block in messages[0]["content"]:
        if block.get("type") == "text":
            return block["text"]
    return ""


def _diff_from_prompt(text: str) -> str:
    m = re.search(r"```diff\n(.*)\n```", text, re.S)
    return m.group(1) if m else ""


def _findings(diff: str) -> list[dict]:
    parsed = parse_unified_diff(diff)
    added_text: dict[tuple[str, int], str] = {}
    # re-walk the diff to get the text of each added line
    path, new_line = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            t = raw[4:].strip()
            path = t[2:] if t.startswith("b/") else t
        elif raw.startswith("@@"):
            new_line = int(re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw).group(1))
        elif path and raw.startswith("+") and not raw.startswith("+++"):
            added_text[(path, new_line)] = raw[1:]
            new_line += 1
        elif path and not raw.startswith("-") and not raw.startswith("\\") and new_line:
            new_line += 1
    out = []
    for (p, line), text in sorted(added_text.items()):
        if p not in parsed:
            continue
        for rx, cat, sev, body, fix in _RULES:
            if rx.search(text):
                out.append({"path": p, "line": line, "severity": sev, "category": cat,
                            "body": body, "suggestion": fix, "confidence": 0.8})
                break
    return out


def mock_reviewer() -> ScriptedLLM:
    def script(_call: int, messages: list[dict], tools) -> LLMResponse:
        i = sum(1 for m in messages if m["role"] == "assistant")  # step within THIS review
        diff = _diff_from_prompt(_first_user_text(messages))
        files = sorted(parse_unified_diff(diff))
        tool_names = {t.name for t in tools}
        if i == 0 and files and "search_code" in tool_names:
            stem = re.sub(r"\W", " ", files[0].rsplit("/", 1)[-1].split(".")[0])
            return LLMResponse(tool_calls=[ToolCall("m0", "search_code", {"query": stem})])
        if i == 1 and files and "read_file" in tool_names:
            return LLMResponse(tool_calls=[ToolCall("m1", "read_file", {"path": files[0]})])
        findings = _findings(diff)
        summary = (
            f"[mock provider] Rule-based stand-in reviewed {len(files)} file(s) and found "
            f"{len(findings)} candidate issue(s). Use a real LLM provider for actual reviews."
        )
        return LLMResponse(tool_calls=[ToolCall(f"m{i}", "submit_review", {"summary": summary, "comments": findings})])

    return ScriptedLLM(script)
