"""`devpilot review` — review your local changes from the terminal. No GitHub needed."""
from __future__ import annotations

import argparse
import json
import logging
import os
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
    r.add_argument("--provider", default=os.getenv("DEVPILOT_PROVIDER", "anthropic"), choices=["anthropic", "openai", "gemini", "mock"])
    r.add_argument("--model", default=None)
    r.add_argument("--format", default="text", choices=["text", "json"])
    r.add_argument("--min-confidence", type=float, default=0.5)
    r.add_argument("--fail-on", choices=["critical", "major", "never"], default="never",
                   help="exit 1 if a comment at/above this severity is found (for pre-push hooks / CI)")
    r.add_argument("-v", "--verbose", action="store_true")
    c = sub.add_parser("check", help="review a single file or pasted code (no git needed)")
    c.add_argument("file", nargs="?", default="-", help="file to review, or - to read pasted code from stdin (default)")
    c.add_argument("--name", help="file name for pasted code, e.g. app.py (helps detect the language)")
    c.add_argument("--fix", action="store_true", help="also produce a fixed version and show the changes")
    c.add_argument("--write", action="store_true", help="with --fix: save the fixed code next to the file as <name>.fixed<ext>")
    c.add_argument("--provider", default=os.getenv("DEVPILOT_PROVIDER", "anthropic"), choices=["anthropic", "openai", "gemini", "mock"])
    c.add_argument("--model", default=None)
    c.add_argument("--format", default="text", choices=["text", "json"])
    c.add_argument("-v", "--verbose", action="store_true")
    w = sub.add_parser("web", help="open a local web page where you can paste code for review")
    w.add_argument("--provider", default=os.getenv("DEVPILOT_PROVIDER", "anthropic"), choices=["anthropic", "openai", "gemini", "mock"])
    w.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)
    if args.cmd == "check":
        return _check(args)
    if args.cmd == "web":
        import threading
        import webbrowser

        import uvicorn

        os.environ["DEVPILOT_PROVIDER"] = args.provider
        url = f"http://127.0.0.1:{args.port}"
        print(f"DevPilot is running at {url}  (press Ctrl+C to stop)")
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run("devpilot_agent.app:app", host="127.0.0.1", port=args.port, log_level="warning")
        return 0

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


def _check(args) -> int:
    import pathlib

    from .snippet import fix_code, review_snippet

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(name)s %(message)s")
    if args.file == "-":
        if sys.stdin.isatty():
            print("Paste your code, then press Ctrl+D on a new line:", file=sys.stderr)
        code = sys.stdin.read()
        name = args.name or "pasted_code"
    else:
        path = pathlib.Path(args.file)
        code = path.read_text(encoding="utf-8")
        name = args.name or path.name
    if not code.strip():
        print("No code to review.")
        return 0

    llm = make_client(args.provider, args.model)
    result = review_snippet(ReviewAgent(llm), code, name)
    fixed = diff = notes = None
    if args.fix:
        fixed, diff, notes = fix_code(llm, code, name, result)

    if args.format == "json":
        out = result.model_dump(mode="json")
        if args.fix:
            out.update(fixed_code=fixed, diff=diff, fix_notes=notes)
        print(json.dumps(out, indent=2))
        return 0

    print(render_text(result))
    if args.fix:
        print("\n" + "=" * 60 + "\nSuggested changes\n" + "=" * 60)
        print(diff or "No changes needed.")
        if notes:
            print(f"\n{notes}")
        if args.write and diff and args.file != "-":
            src = pathlib.Path(args.file)
            target = src.with_name(f"{src.stem}.fixed{src.suffix}")
            target.write_text(fixed, encoding="utf-8")
            print(f"\nFixed code saved to {target} (your original file was not changed)")
        elif diff and args.file == "-":
            print("\n--- Full fixed code ---\n" + fixed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
