"""End-to-end test of GitHub Action mode against the fake GitHub API in scripts/fake_github.py."""
import importlib.util
import json
import pathlib
import threading
from http.server import HTTPServer

import httpx

from devpilot_agent import github_action
from devpilot_agent.models import ReviewComment, ReviewResult
from devpilot_agent.repo import GitHubRepo

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _fake_github():
    spec = importlib.util.spec_from_file_location("fake_github", ROOT / "scripts" / "fake_github.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REVIEWS.clear()
    server = HTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return mod, server


def test_action_reviews_pr_and_posts_inline_comments(tmp_path, monkeypatch, capsys):
    mod, server = _fake_github()
    try:
        api = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setattr(GitHubRepo, "API", api)
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"action": "opened", "pull_request": {"number": 42, "draft": False}}))
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        monkeypatch.setenv("GITHUB_REPOSITORY", "yaswanth0702/demo")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        monkeypatch.setenv("DEVPILOT_PROVIDER", "mock")

        assert github_action.main() == 0

        assert len(mod.REVIEWS) == 1
        review = mod.REVIEWS[0]
        assert review["event"] == "COMMENT" and review["commit_id"] == mod.HEAD_SHA
        assert github_action.MARKER in review["body"]
        [c] = review["comments"]
        assert (c["path"], c["line"], c["side"]) == ("app/users.py", 3, "RIGHT")
        assert "SQL injection" in c["body"] and "Suggested fix" in c["body"]
        assert "DevPilot review" in summary.read_text()
    finally:
        server.shutdown()


def test_fail_on_critical(tmp_path, monkeypatch):
    mod, server = _fake_github()
    try:
        monkeypatch.setattr(GitHubRepo, "API", f"http://127.0.0.1:{server.server_port}")
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 42}}))
        for k, v in {"GITHUB_EVENT_PATH": str(event), "GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "yaswanth0702/demo",
                     "DEVPILOT_PROVIDER": "mock", "DEVPILOT_FAIL_ON_CRITICAL": "true"}.items():
            monkeypatch.setenv(k, v)
        assert github_action.main() == 1
    finally:
        server.shutdown()


def test_skips_drafts_and_non_pr_events(tmp_path, monkeypatch, capsys):
    event = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    event.write_text(json.dumps({"pull_request": {"number": 1, "draft": True}}))
    assert github_action.main() == 0
    event.write_text(json.dumps({"ref": "refs/heads/main"}))
    assert github_action.main() == 0
    assert "Draft PR" in capsys.readouterr().out


def test_falls_back_to_body_when_github_rejects_lines():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(422 if body["comments"] else 200, json={})

    result = ReviewResult(summary="s", comments=[ReviewComment(
        path="a.py", line=99, severity="major", category="bug", body="something is broken here", confidence=0.9)])
    mode = github_action.post_review(httpx.Client(transport=httpx.MockTransport(handler)), "https://api", "o", "r", 1,
                                     "sha", result, "m")
    assert mode == "body" and len(calls) == 2
    assert calls[1]["comments"] == [] and "a.py:99" in calls[1]["body"]
