"""The review agent: a bounded tool-use loop that ends with a structured review."""
from __future__ import annotations

import logging
import time

from pydantic import ValidationError

from .diff_parser import parse_unified_diff
from .llm import LLMClient, LLMError
from .models import ReviewComment, ReviewResult
from .repo import Repo
from .tools import ALL_TOOLS, SUBMIT_REVIEW, ToolExecutor
from .verifier import VerifierConfig, verify

log = logging.getLogger("devpilot.agent")

SYSTEM_PROMPT = """You are DevPilot, a senior software engineer reviewing a pull request.

Goal: find real defects a careful human reviewer would flag: bugs, security holes (injection,
secrets, authz), concurrency issues, resource leaks, broken error handling, serious performance
problems, and missing tests for risky logic.

How to work:
1. Read the diff. For anything unclear, use read_file to see surrounding code and search_code to
   find callers or definitions. Investigate before you claim something is a bug.
2. Only comment on lines that were ADDED or MODIFIED in this PR (line numbers in the new file).
3. Each comment must be specific: what breaks, under what input, and a concrete fix.
4. Do not comment on formatting, naming taste, or anything a linter catches.
5. Set confidence honestly. If you are guessing, use < 0.5 or leave it out.
6. Finish by calling submit_review exactly once. An empty comment list is a valid review.
"""

MAX_DIFF_CHARS = 60_000


class IncompleteReviewError(LLMError):
    """The reviewer did not submit a usable final result within its budget."""


class ReviewAgent:
    def __init__(self, llm: LLMClient, max_steps: int = 8, verifier_cfg: VerifierConfig | None = None):
        self.llm = llm
        self.max_steps = max_steps
        self.verifier_cfg = verifier_cfg or VerifierConfig()

    def review(self, repo: Repo) -> ReviewResult:
        started = time.monotonic()
        diff_text = repo.diff()
        parsed = parse_unified_diff(diff_text)
        executor = ToolExecutor(repo)

        shown = diff_text if len(diff_text) <= MAX_DIFF_CHARS else diff_text[:MAX_DIFF_CHARS] + "\n... (diff truncated)"
        messages: list[dict] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Changed files: {', '.join(sorted(parsed)) or '(none)'}\n\n```diff\n{shown}\n```",
                    }
                ],
            }
        ]

        steps = tool_calls = in_tok = out_tok = 0
        submission = None

        while steps < self.max_steps and submission is None:
            last_step = steps == self.max_steps - 1
            tools = [SUBMIT_REVIEW] if last_step else ALL_TOOLS
            if last_step:
                messages.append({"role": "user", "content": [{"type": "text", "text": "Step limit reached. Call submit_review now."}]})

            resp = self.llm.complete(SYSTEM_PROMPT, _merge_consecutive_user(messages), tools)
            steps += 1
            in_tok += resp.input_tokens
            out_tok += resp.output_tokens
            messages.append(resp.as_assistant_message())

            if not resp.tool_calls:
                messages.append({"role": "user", "content": [{"type": "text", "text": "Use a tool, or call submit_review to finish."}]})
                continue

            results = []
            for call in resp.tool_calls:
                tool_calls += 1
                if call.name == SUBMIT_REVIEW.name:
                    if submission is None:
                        submission = _parse_submission(call.input)
                    received = submission is not None
                    results.append({
                        "type": "tool_result", "tool_use_id": call.id, "is_error": not received,
                        "content": "review received" if received else
                        "Submit a non-empty summary and a list of valid comments. Use [] for a clean review.",
                    })
                    continue
                output, is_error = executor.run(call.name, call.input)
                log.debug("tool %s(%s) -> %d chars", call.name, call.input, len(output))
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": is_error})
            messages.append({"role": "user", "content": results})

        if submission is None:
            raise IncompleteReviewError(
                f"Review incomplete: the model did not submit a valid final review within {self.max_steps} steps."
            )
        summary, raw_comments, parse_drops = submission
        kept, dropped = verify(raw_comments, parsed, self.verifier_cfg)
        log.info(
            "review done steps=%d tools=%d kept=%d dropped=%d %.1fs",
            steps, tool_calls, len(kept), len(dropped) + parse_drops, time.monotonic() - started,
        )
        return ReviewResult(
            summary=summary,
            comments=kept,
            dropped=dropped,
            steps=steps,
            tool_calls=tool_calls,
            input_tokens=in_tok,
            output_tokens=out_tok,
        )


def _parse_submission(payload: dict) -> tuple[str, list[ReviewComment], int] | None:
    if not isinstance(payload, dict):
        return None
    summary, raw = payload.get("summary"), payload.get("comments")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(raw, list):
        return None

    valid: list[ReviewComment] = []
    for item in raw:
        try:
            valid.append(ReviewComment.model_validate(item))
        except ValidationError:
            continue
    # Distinguish an explicit clean review from a payload containing only invalid findings.
    if raw and not valid:
        return None
    return summary.strip(), valid, len(raw) - len(valid)


def _merge_consecutive_user(messages: list[dict]) -> list[dict]:
    """Anthropic requires alternating roles; fold adjacent user turns together."""
    merged: list[dict] = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"] == "user":
            merged[-1] = {"role": "user", "content": merged[-1]["content"] + m["content"]}
        else:
            merged.append(m)
    return merged
