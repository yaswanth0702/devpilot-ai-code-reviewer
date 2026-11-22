from devpilot_agent.diff_parser import parse_unified_diff
from devpilot_agent.models import ReviewComment
from evals.cases import CASES
from evals.run_eval import build_diff, score_case


def test_every_expected_line_is_an_added_line():
    for case in CASES:
        added = parse_unified_diff(build_diff(case["path"], case["before"], case["after"]))[case["path"]].added_lines
        for e in case["expected"]:
            assert e["line"] in added, case["id"]


def test_scoring_tolerance_and_false_positives():
    case = {"path": "a.py", "expected": [{"line": 10, "category": "bug"}]}
    mk = lambda line, cat="bug": ReviewComment(path="a.py", line=line, severity="major", category=cat, body="x" * 20, confidence=0.9)
    assert score_case(case, [mk(12)]) == {"tp": 1, "fp": 0, "fn": 0, "category_correct": 1}
    assert score_case(case, [mk(13, "security")]) == {"tp": 0, "fp": 1, "fn": 1, "category_correct": 0}
    assert score_case(case, [mk(10), mk(11)]) == {"tp": 1, "fp": 1, "fn": 0, "category_correct": 1}
