"""Guardrail between the model and the developer.

LLM reviewers tend to (a) comment on lines the PR didn't touch, (b) hallucinate file paths,
(c) repeat themselves and (d) flood PRs with low-value nits. The verifier enforces hard rules
so that only grounded, actionable comments get posted. Every drop is recorded with a reason,
which feeds the eval report.
"""
from __future__ import annotations

from dataclasses import dataclass

from .diff_parser import FileDiff
from .models import DroppedComment, ReviewComment, Severity

_SEVERITY_RANK = {Severity.critical: 0, Severity.major: 1, Severity.minor: 2, Severity.nit: 3}


@dataclass
class VerifierConfig:
    min_confidence: float = 0.5
    max_comments: int = 12
    allow_nits: bool = False
    snap_distance: int = 2  # move a comment onto the nearest added line if it's this close
    min_body_chars: int = 15


def verify(
    comments: list[ReviewComment], diff: dict[str, FileDiff], cfg: VerifierConfig | None = None
) -> tuple[list[ReviewComment], list[DroppedComment]]:
    cfg = cfg or VerifierConfig()
    kept: list[ReviewComment] = []
    dropped: list[DroppedComment] = []
    seen: set[tuple[str, int, str]] = set()

    def drop(c: ReviewComment, reason: str) -> None:
        dropped.append(DroppedComment(comment=c, reason=reason))

    for c in comments:
        fd = diff.get(c.path)
        if fd is None:
            drop(c, "file_not_in_diff")
            continue
        if c.line not in fd.added_lines:
            nearest = min(fd.added_lines, key=lambda n: abs(n - c.line), default=None)
            if nearest is not None and abs(nearest - c.line) <= cfg.snap_distance:
                c = c.model_copy(update={"line": nearest})
            else:
                drop(c, "line_not_changed")
                continue
        if c.confidence < cfg.min_confidence:
            drop(c, "low_confidence")
            continue
        if c.severity == Severity.nit and not cfg.allow_nits:
            drop(c, "nit_filtered")
            continue
        if len(c.body.strip()) < cfg.min_body_chars:
            drop(c, "not_actionable")
            continue
        key = (c.path, c.line, c.category.value)
        if key in seen:
            drop(c, "duplicate")
            continue
        seen.add(key)
        kept.append(c)

    kept.sort(key=lambda c: (_SEVERITY_RANK[c.severity], -c.confidence))
    for c in kept[cfg.max_comments :]:
        drop(c, "over_limit")
    return kept[: cfg.max_comments], dropped
