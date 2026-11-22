"""Run DevPilot inside GitHub Actions: review a pull request (inline review) or a direct push
(commit comment), and post the result.

Reads the standard Actions environment (GITHUB_EVENT_PATH, GITHUB_REPOSITORY, GITHUB_TOKEN),
reviews the PR with the configured provider, and posts ONE review with inline comments.

    python -m devpilot_agent.github_action
"""
from __future__ import annotations

import json
import logging
import os
import sys

import httpx

from .agent import ReviewAgent
from .llm import make_client
from .models import ReviewComment, ReviewResult
from .repo import GitHubCommitRepo, GitHubRepo
from .verifier import VerifierConfig

log = logging.getLogger("devpilot.action")
MARKER = "<!-- devpilot-review -->"


def format_comment(c: ReviewComment) -> str:
    text = f"**{c.severity.value.upper()}** · {c.category.value}\n\n{c.body}"
    if c.suggestion:
        text += f"\n\n**Suggested fix:** {c.suggestion}"
    return text + f"\n\n<sub>DevPilot · confidence {c.confidence:.2f}</sub>"


def format_summary(r: ReviewResult, model: str) -> str:
    lines = [MARKER, "### 🤖 DevPilot review", "", r.summary, ""]
    if not r.comments:
        lines.append("No issues found in the changed lines.")
    lines.append(
        f"<sub>{len(r.comments)} comment(s) · {len(r.dropped)} filtered by verifier · "
        f"{r.tool_calls} tool calls · model `{model}`</sub>"
    )
    return "\n".join(lines)


def post_review(client: httpx.Client, api: str, owner: str, repo: str, pr: int, head_sha: str,
                result: ReviewResult, model: str) -> str:
    """Post inline comments; if GitHub rejects a line (422), fall back to listing them in the body."""
    url = f"{api}/repos/{owner}/{repo}/pulls/{pr}/reviews"
    body = {
        "commit_id": head_sha,
        "event": "COMMENT",  # never approve or block: a human stays in charge
        "body": format_summary(result, model),
        "comments": [{"path": c.path, "line": c.line, "side": "RIGHT", "body": format_comment(c)} for c in result.comments],
    }
    r = client.post(url, json=body)
    if r.status_code == 422 and result.comments:
        log.warning("GitHub rejected inline comments (%s); posting them in the review body", r.text[:200])
        listed = "\n\n".join(f"**`{c.path}:{c.line}`** {format_comment(c)}" for c in result.comments)
        body["comments"] = []
        body["body"] = body["body"] + "\n\n---\n\n" + listed
        r = client.post(url, json=body)
    r.raise_for_status()
    return "inline" if body["comments"] else "body"


def format_commit_comment(r: ReviewResult, model: str, server: str, owner: str, repo: str, sha: str) -> str:
    """Commit comments can't be anchored to diff lines reliably, so issues are listed with links."""
    lines = [format_summary(r, model)]
    for c in r.comments:
        link = f"{server}/{owner}/{repo}/blob/{sha}/{c.path}#L{c.line}"
        lines += ["", "---", "", f"[`{c.path}:{c.line}`]({link}) " + format_comment(c)]
    return "\n".join(lines)


def _api_client(token: str) -> httpx.Client:
    return httpx.Client(timeout=30, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })


def _make_agent():
    provider = os.getenv("DEVPILOT_PROVIDER", "gemini")
    llm = make_client(provider, os.getenv("DEVPILOT_MODEL") or None)
    agent = ReviewAgent(
        llm,
        max_steps=int(os.getenv("DEVPILOT_MAX_STEPS", "8")),
        verifier_cfg=VerifierConfig(min_confidence=float(os.getenv("DEVPILOT_MIN_CONFIDENCE", "0.5"))),
    )
    return agent, provider, getattr(llm, "model", provider)


def _finish(result: ReviewResult, model: str) -> int:
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a") as f:
            f.write(format_summary(result, model) + "\n")
    if os.getenv("DEVPILOT_FAIL_ON_CRITICAL", "false") == "true" and any(c.severity.value == "critical" for c in result.comments):
        print("Critical issue found; failing the check (fail-on-critical is on).")
        return 1
    return 0


def review_push(event: dict, token: str) -> int:
    after, before = event.get("after"), event.get("before")
    if event.get("deleted") or not after or after == GitHubCommitRepo.ZERO:
        print("Branch deleted; nothing to review.")
        return 0
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
    client = _api_client(token)

    # Code that arrived through a merged pull request was already reviewed on the PR.
    pulls = client.get(f"{GitHubRepo.API}/repos/{owner}/{repo}/commits/{after}/pulls")
    if pulls.status_code == 200 and any(p.get("merged_at") for p in pulls.json()):
        print("Push comes from a merged pull request that was already reviewed; skipping.")
        return 0

    agent, provider, model = _make_agent()
    target = GitHubCommitRepo(owner, repo, before, after, token)
    if not target.diff().strip():
        print("No code changes in this push.")
        return 0
    print(f"DevPilot reviewing push {before[:7] if before else '(new)'}..{after[:7]} on {owner}/{repo} with {provider} ({model})")
    result = agent.review(target)
    print(f"{len(result.comments)} comment(s), {len(result.dropped)} filtered, {result.tool_calls} tool calls")

    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    r = client.post(f"{GitHubRepo.API}/repos/{owner}/{repo}/commits/{after}/comments",
                    json={"body": format_commit_comment(result, model, server, owner, repo, after)})
    r.raise_for_status()
    print("Review posted as a commit comment.")
    return _finish(result, model)


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    token = os.environ.get("GITHUB_TOKEN")
    if not event_path or not token:
        print("GITHUB_EVENT_PATH and GITHUB_TOKEN are required (run inside GitHub Actions).", file=sys.stderr)
        return 2
    event = json.load(open(event_path))
    if os.getenv("GITHUB_EVENT_NAME") == "push" or ("after" in event and "pull_request" not in event):
        return review_push(event, token)
    pr = event.get("pull_request")
    if not pr:
        print("Not a pull_request or push event; nothing to review.")
        return 0
    if pr.get("draft") and os.getenv("DEVPILOT_REVIEW_DRAFTS", "false") != "true":
        print("Draft PR; skipping.")
        return 0

    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
    number = int(pr["number"])
    agent, provider, model = _make_agent()
    print(f"DevPilot reviewing {owner}/{repo}#{number} with {provider} ({model})")

    gh = GitHubRepo(owner, repo, number, token)
    result = agent.review(gh)
    print(f"{len(result.comments)} comment(s), {len(result.dropped)} filtered, {result.tool_calls} tool calls")

    mode = post_review(_api_client(token), GitHubRepo.API, owner, repo, number, gh.head_sha, result, model)
    print(f"Review posted ({mode} comments).")
    return _finish(result, model)


if __name__ == "__main__":
    sys.exit(main())
