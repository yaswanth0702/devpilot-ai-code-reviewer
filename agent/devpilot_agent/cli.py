"""`devpilot review` — review your local changes from the terminal. No GitHub needed."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .agent import ReviewAgent
from .llm import make_client
from .models import ReviewResult, Severity
from .repo import LocalGitRepo
from .verifier import VerifierConfig

_ICON = {"critical": "[CRITICAL]", "major": "[MAJOR]", "minor": "[minor]", "nit": "[nit]"}


def render_text(r: ReviewResult) -> str:
    lines = ["DevPilot review", "=" * 60, r.summary, ""]
    if not r.comments:
        lines.append("No issues found.")
    for c in r.comments:
        lines.append(f"{_ICON[c.severity.value]} {c.path}:{c.line}  ({c.category.value}, confidence {c.confidence:.2f})")
        lines.append(f"    {c.body}")
        if c.suggestion:
            lines.append(f"    fix: {c.suggestion}")
        lines.append("")
    lines.append(
        f"steps={r.steps} tool_calls={r.tool_calls} kept={len(r.comments)} "
        f"filtered_by_verifier={len(r.dropped)} tokens={r.input_tokens}+{r.output_tokens}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="devpilot", description="AI code review for your local git changes")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="review changes in a git repo")
    r.add_argument("path", nargs="?", default=".", help="path inside a git repo (default: .)")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--base", help="review current branch against this base, e.g. main")
    g.add_argument("--staged", action="store_true", help="review staged changes only")
    r.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "gemini", "mock"])
    r.add_argument("--model", default=None)
    r.add_argument("--format", default="text", choices=["text", "json"])
    r.add_argument("--min-confidence", type=float, default=0.5)
    r.add_argument("--fail-on", choices=["critical", "major", "never"], default="never",
                   help="exit 1 if a comment at/above this severity is found (for pre-push hooks / CI)")
    r.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(name)s %(message)s")
    repo = LocalGitRepo(args.path, base=args.base, staged=args.staged)
    if not repo.diff().strip():
        print("No changes to review.")
        return 0

    agent = ReviewAgent(make_client(args.provider, args.model), verifier_cfg=VerifierConfig(min_confidence=args.min_confidence))
    result = agent.review(repo)
    print(result.model_dump_json(indent=2) if args.format == "json" else render_text(result))

    if args.fail_on != "never":
        threshold = {"critical": {Severity.critical}, "major": {Severity.critical, Severity.major}}[args.fail_on]
        if any(c.severity in threshold for c in result.comments):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
