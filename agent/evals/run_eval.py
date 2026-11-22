"""Run the seeded-bug benchmark and write a report.

    python -m evals.run_eval --provider mock          # offline rule-based baseline
    python -m evals.run_eval --provider anthropic     # needs ANTHROPIC_API_KEY
    python -m evals.run_eval --provider openai        # needs OPENAI_API_KEY
"""
from __future__ import annotations

import argparse
import difflib
import json
import pathlib
import statistics
import time
from datetime import datetime, timezone

from devpilot_agent.agent import ReviewAgent
from devpilot_agent.llm import make_client
from devpilot_agent.repo import InMemoryRepo

from .cases import CASES

LINE_TOLERANCE = 2
RESULTS_DIR = pathlib.Path(__file__).parent / "results"


def build_diff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}", n=3
    )
    return f"diff --git a/{path} b/{path}\n" + "".join(lines)


def score_case(case: dict, comments: list) -> dict:
    expected = list(case["expected"])
    matched_exp: set[int] = set()
    tp = fp = cat_ok = 0
    for c in comments:
        hit = next(
            (i for i, e in enumerate(expected)
             if i not in matched_exp and c.path == case["path"] and abs(c.line - e["line"]) <= LINE_TOLERANCE),
            None,
        )
        if hit is None:
            fp += 1
        else:
            matched_exp.add(hit)
            tp += 1
            cat_ok += int(c.category.value == expected[hit]["category"])
    return {"tp": tp, "fp": fp, "fn": len(expected) - len(matched_exp), "category_correct": cat_ok}


def run(provider: str, model: str | None, repeats: int = 1) -> dict:
    agent = ReviewAgent(make_client(provider, model))
    rows = []
    for case in CASES:
        for _ in range(repeats):
            diff = build_diff(case["path"], case["before"], case["after"])
            repo = InMemoryRepo(diff, {case["path"]: case["after"]})
            t0 = time.monotonic()
            result = agent.review(repo)
            elapsed = time.monotonic() - t0
            s = score_case(case, result.comments)
            rows.append({
                "id": case["id"], **s, "seconds": round(elapsed, 2), "tool_calls": result.tool_calls,
                "tokens": result.input_tokens + result.output_tokens, "filtered": len(result.dropped),
                "comments": [c.model_dump(mode="json") for c in result.comments],
            })
            print(f"{case['id']:<32} tp={s['tp']} fp={s['fp']} fn={s['fn']}  {elapsed:.1f}s  tools={result.tool_calls}")

    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    clean = [r for r in rows if r["id"].startswith("clean-")]
    return {
        "provider": provider,
        "model": model or getattr(agent.llm, "model", provider),
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases": len(CASES),
        "repeats": repeats,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        "category_accuracy": round(sum(r["category_correct"] for r in rows) / tp, 3) if tp else 0.0,
        "clean_cases_with_false_positives": sum(1 for r in clean if r["fp"] > 0),
        "clean_cases": len(clean),
        "comments_filtered_by_verifier": sum(r["filtered"] for r in rows),
        "median_seconds": statistics.median(r["seconds"] for r in rows),
        "avg_tool_calls": round(statistics.mean(r["tool_calls"] for r in rows), 2),
        "total_tokens": sum(r["tokens"] for r in rows),
        "rows": rows,
    }


def to_markdown(rep: dict) -> str:
    out = [
        f"# DevPilot eval: `{rep['provider']}` ({rep['model']})",
        "",
        f"Run at {rep['run_at']} on {rep['cases']} cases x {rep['repeats']} repeat(s).",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Precision | {rep['precision']:.3f} |",
        f"| Recall | {rep['recall']:.3f} |",
        f"| F1 | {rep['f1']:.3f} |",
        f"| Category accuracy (of true positives) | {rep['category_accuracy']:.3f} |",
        f"| Clean PRs with a false positive | {rep['clean_cases_with_false_positives']} / {rep['clean_cases']} |",
        f"| Comments filtered by verifier | {rep['comments_filtered_by_verifier']} |",
        f"| Median seconds per review | {rep['median_seconds']} |",
        f"| Avg tool calls per review | {rep['avg_tool_calls']} |",
        f"| Total tokens | {rep['total_tokens']} |",
        "",
        "| Case | TP | FP | FN | Seconds | Tool calls |", "|---|---|---|---|---|---|",
    ]
    for r in rep["rows"]:
        out.append(f"| {r['id']} | {r['tp']} | {r['fp']} | {r['fn']} | {r['seconds']} | {r['tool_calls']} |")
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="mock", choices=["mock", "anthropic", "openai"])
    p.add_argument("--model")
    p.add_argument("--repeats", type=int, default=1)
    args = p.parse_args()
    rep = run(args.provider, args.model, args.repeats)
    RESULTS_DIR.mkdir(exist_ok=True)
    stem = f"{args.provider}{'-' + args.model if args.model else ''}"
    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(rep, indent=2))
    (RESULTS_DIR / f"{stem}.md").write_text(to_markdown(rep))
    print(f"\nprecision={rep['precision']} recall={rep['recall']} f1={rep['f1']}  -> evals/results/{stem}.md")


if __name__ == "__main__":
    main()
