from devpilot_agent.diff_parser import parse_unified_diff
from devpilot_agent.models import ReviewComment
from devpilot_agent.verifier import VerifierConfig, verify


def c(path="src/UserService.java", line=11, severity="major", category="bug", conf=0.9, body="Reference comparison of strings is wrong here."):
    return ReviewComment(path=path, line=line, severity=severity, category=category, body=body, confidence=conf)


def reasons(dropped):
    return [d.reason for d in dropped]


def test_keeps_grounded_comment(sample_diff):
    kept, dropped = verify([c()], parse_unified_diff(sample_diff))
    assert len(kept) == 1 and not dropped


def test_drops_hallucinated_file(sample_diff):
    kept, dropped = verify([c(path="src/Nope.java")], parse_unified_diff(sample_diff))
    assert not kept and reasons(dropped) == ["file_not_in_diff"]


def test_drops_unchanged_line_but_snaps_near_miss(sample_diff):
    diff = parse_unified_diff(sample_diff)
    kept, dropped = verify([c(line=40), c(line=16, category="security")], diff)
    assert reasons(dropped) == ["line_not_changed"]
    assert kept[0].line == 14  # snapped from 16 to nearest added line


def test_confidence_nits_duplicates_and_vague(sample_diff):
    diff = parse_unified_diff(sample_diff)
    kept, dropped = verify(
        [c(), c(), c(conf=0.2, category="security"), c(severity="nit", category="maintainability"), c(body="bad", category="testing")],
        diff,
    )
    assert len(kept) == 1
    assert sorted(reasons(dropped)) == ["duplicate", "low_confidence", "nit_filtered", "not_actionable"]


def test_orders_by_severity_and_caps(sample_diff):
    diff = parse_unified_diff(sample_diff)
    cats = ["bug", "security", "performance", "concurrency"]
    items = [c(line=11 + i, category=cats[i], severity=s) for i, s in enumerate(["minor", "critical", "major", "minor"])]
    kept, dropped = verify(items, diff, VerifierConfig(max_comments=2))
    assert [k.severity.value for k in kept] == ["critical", "major"]
    assert reasons(dropped).count("over_limit") == 2
