"""HTTP API used by the Spring Boot gateway (GitHub mode)."""
from __future__ import annotations

import logging
import os
import threading
import time

from fastapi import FastAPI, HTTPException

from .agent import ReviewAgent
from .llm import LLMError, make_client
from .models import ReviewRequest, ReviewResult
from .repo import GitHubRepo, InMemoryRepo
from .verifier import VerifierConfig

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="DevPilot Agent", version="1.0.0")

_metrics = {"reviews_total": 0, "reviews_failed": 0, "comments_posted": 0, "comments_filtered": 0, "review_seconds_sum": 0.0}
_lock = threading.Lock()


def _agent() -> ReviewAgent:
    provider = os.getenv("DEVPILOT_PROVIDER", "anthropic")
    return ReviewAgent(
        make_client(provider, os.getenv("DEVPILOT_MODEL")),
        max_steps=int(os.getenv("DEVPILOT_MAX_STEPS", "8")),
        verifier_cfg=VerifierConfig(min_confidence=float(os.getenv("DEVPILOT_MIN_CONFIDENCE", "0.5"))),
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "provider": os.getenv("DEVPILOT_PROVIDER", "anthropic")}


@app.get("/metrics")
def metrics() -> dict:
    with _lock:
        return dict(_metrics)


@app.post("/review", response_model=ReviewResult)
def review(req: ReviewRequest) -> ReviewResult:
    if req.diff is not None:
        repo = InMemoryRepo(req.diff, req.files or {})
    elif req.owner and req.repo and req.pr_number:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise HTTPException(500, "GITHUB_TOKEN not configured on the agent service")
        repo = GitHubRepo(req.owner, req.repo, req.pr_number, token)
    else:
        raise HTTPException(422, "provide either diff (+files) or owner/repo/pr_number")

    started = time.monotonic()
    try:
        result = _agent().review(repo)
    except LLMError as e:
        with _lock:
            _metrics["reviews_failed"] += 1
        raise HTTPException(502, f"LLM provider error: {e}") from e
    with _lock:
        _metrics["reviews_total"] += 1
        _metrics["comments_posted"] += len(result.comments)
        _metrics["comments_filtered"] += len(result.dropped)
        _metrics["review_seconds_sum"] += time.monotonic() - started
    return result
