"""Review a standalone piece of code (a file or pasted text), and optionally produce a fixed version.

The code is treated as a brand-new file, so every line is reviewable. `fix_code` asks the model to
apply the review's fixes and return the full corrected file; the result is shown as a diff so the
developer can see exactly what changed before using it.
"""
from __future__ import annotations

import difflib

from .agent import ReviewAgent
from .llm import LLMClient, ToolSpec
from .models import ReviewResult
from .repo import InMemoryRepo

MAX_SNIPPET_CHARS = 60_000

SUBMIT_FIXED_CODE = ToolSpec(
    name="submit_fixed_code",
    description="Return the complete corrected file.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The full file content after applying the fixes."},
            "notes": {"type": "string", "description": "One line per change made."},
        },
        "required": ["code"],
    },
)

FIX_PROMPT = """You are fixing code after a code review.

Apply ONLY the fixes for the issues listed below. Keep everything else exactly as it is: same
structure, names, formatting, comments and behaviour. Do not refactor or restyle unrelated code.
Return the COMPLETE corrected file by calling submit_fixed_code exactly once."""


def snippet_diff(code: str, filename: str) -> str:
    """A unified diff that adds the whole file, so every line can be reviewed."""
    lines = difflib.unified_diff([], code.splitlines(keepends=True), fromfile="/dev/null", tofile=f"b/{filename}", n=0)
    return f"diff --git a/{filename} b/{filename}\nnew file mode 100644\n" + "".join(lines)


def review_snippet(agent: ReviewAgent, code: str, filename: str) -> ReviewResult:
    if not code.strip():
        raise ValueError("no code to review")
    if len(code) > MAX_SNIPPET_CHARS:
        raise ValueError(f"code is too long ({len(code)} chars, max {MAX_SNIPPET_CHARS})")
    if not code.endswith("\n"):
        code += "\n"
    return agent.review(InMemoryRepo(snippet_diff(code, filename), {filename: code}))


def fix_code(llm: LLMClient, code: str, filename: str, review: ReviewResult) -> tuple[str, str, str]:
    """Returns (fixed_code, unified_diff, notes). If there is nothing to fix, returns the input unchanged."""
    if not review.comments:
        return code, "", "No issues to fix."
    issues = "\n".join(
        f"- line {c.line} [{c.severity.value}/{c.category.value}]: {c.body}"
        + (f"\n  suggested fix: {c.suggestion}" if c.suggestion else "")
        for c in review.comments
    )
    numbered = "\n".join(f"{i:>5}  {line}" for i, line in enumerate(code.splitlines(), 1))
    messages = [{
        "role": "user",
        "content": [{"type": "text", "text": f"File: {filename}\n\nIssues to fix:\n{issues}\n\n"
                                             f"Current file (line numbers are for reference only, do not include them):\n{numbered}"}],
    }]
    resp = llm.complete(FIX_PROMPT, messages, [SUBMIT_FIXED_CODE])
    call = next((c for c in resp.tool_calls if c.name == SUBMIT_FIXED_CODE.name), None)
    if call is None or not isinstance(call.input.get("code"), str) or not call.input["code"].strip():
        raise RuntimeError("the model did not return fixed code")
    fixed = call.input["code"]
    if not fixed.endswith("\n"):
        fixed += "\n"
    original = code if code.endswith("\n") else code + "\n"
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), fixed.splitlines(keepends=True),
        fromfile=f"{filename} (original)", tofile=f"{filename} (fixed)",
    ))
    return fixed, diff, call.input.get("notes", "")
