from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"
    nit = "nit"


class Category(str, Enum):
    bug = "bug"
    security = "security"
    performance = "performance"
    concurrency = "concurrency"
    error_handling = "error_handling"
    maintainability = "maintainability"
    testing = "testing"


class ReviewComment(BaseModel):
    path: str
    line: int = Field(description="Line number in the NEW version of the file")
    severity: Severity
    category: Category
    body: str
    suggestion: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class ReviewRequest(BaseModel):
    """Either point at a GitHub PR, or pass a raw diff + file contents (local mode / evals)."""

    owner: str | None = None
    repo: str | None = None
    pr_number: int | None = None
    diff: str | None = None
    files: dict[str, str] | None = None


class DroppedComment(BaseModel):
    comment: ReviewComment
    reason: str


class ReviewResult(BaseModel):
    summary: str
    comments: list[ReviewComment]
    dropped: list[DroppedComment] = []
    steps: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
