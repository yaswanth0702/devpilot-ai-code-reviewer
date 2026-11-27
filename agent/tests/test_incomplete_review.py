"""A missing final submission must never look like a completed, clean review."""
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from devpilot_agent import app as api
from devpilot_agent import cli, github_action
from devpilot_agent.agent import IncompleteReviewError, ReviewAgent
from devpilot_agent.llm import LLMResponse, ScriptedLLM, ToolCall
from devpilot_agent.repo import InMemoryRepo


def unfinished_llm():
    return ScriptedLLM(lambda *_: LLMResponse(text="still reviewing"))


@pytest.mark.parametrize("submission", [
    {}, {"summary": "Looks OK"}, {"summary": "OK", "comments": "none"},
    {"summary": "OK", "comments": [{}]}, {"summary": " ", "comments": []},
])
def test_invalid_submissions_do_not_count_as_clean(sample_diff, submission):
    llm = ScriptedLLM(lambda *_: LLMResponse(tool_calls=[ToolCall("end", "submit_review", submission)]))
    with pytest.raises(IncompleteReviewError, match="Review incomplete"):
        ReviewAgent(llm, max_steps=1).review(InMemoryRepo(sample_diff, {}))


def test_model_can_retry_invalid_submission_and_explicitly_submit_clean_result(sample_diff):
    def script(step, messages, tools):
        payload = {"summary": "OK"} if step == 0 else {"summary": "Reviewed.", "comments": []}
        if step:
            assert messages[-1]["content"][0]["is_error"] is True
        return LLMResponse(tool_calls=[ToolCall(str(step), "submit_review", payload)])

    result = ReviewAgent(ScriptedLLM(script), max_steps=2).review(InMemoryRepo(sample_diff, {}))
    assert result.summary == "Reviewed." and not result.comments


def test_http_incomplete_review_reports_failure_before_suggesting_fixes(monkeypatch):
    monkeypatch.setattr(api, "_agent", lambda: ReviewAgent(unfinished_llm(), max_steps=1))
    client = TestClient(api.app)
    for path, payload in [("/review", {"diff": ""}), ("/check", {"code": "x = 1", "fix": True})]:
        response = client.post(path, json=payload)
        assert response.status_code == 502
        assert "Review incomplete" in response.json()["detail"]
        assert "fixed_code" not in response.json()


def test_cli_returns_nonzero_and_leaves_original_file_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "make_client", lambda *_: unfinished_llm())
    path = tmp_path / "sample.py"
    path.write_text("x = 1\n")
    assert cli.main(["check", str(path), "--fix", "--write"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "Review incomplete" in captured.err
    assert list(tmp_path.iterdir()) == [path]


def test_action_fails_without_posting_an_incomplete_result(tmp_path, sample_diff, monkeypatch, capsys):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"action": "opened", "pull_request": {"number": 1, "head": {"sha": "123"}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_TOKEN", "offline-test")
    monkeypatch.setenv("GITHUB_REPOSITORY", "test/demo")
    monkeypatch.setenv("DEVPILOT_REVIEW_FILES", "all")
    monkeypatch.setattr(github_action, "GitHubRepo", lambda *_args, **_kw: InMemoryRepo(sample_diff, {}))
    monkeypatch.setattr(github_action, "_make_agent", lambda: (ReviewAgent(unfinished_llm(), max_steps=1), "test", "test"))
    post = Mock()
    monkeypatch.setattr(github_action, "post_review", post)
    assert github_action.main() == 2
    assert "Review incomplete" in capsys.readouterr().err
    post.assert_not_called()
