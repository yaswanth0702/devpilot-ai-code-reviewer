import pytest

from devpilot_agent.cli import main
from devpilot_agent.local_apply import approve_replacement


@pytest.mark.parametrize("answer,expected", [("yes", "fixed"), ("n", "source"), ("", "source")])
def test_only_explicit_approval_replaces_file(tmp_path, monkeypatch, answer, expected):
    path = tmp_path / "sample.py"
    path.write_text("source")
    path.chmod(0o750)
    monkeypatch.setattr("builtins.input", lambda _: answer)
    assert approve_replacement(path, b"source", "fixed") == 0
    assert path.read_text() == expected
    assert path.stat().st_mode & 0o777 == 0o750


def test_edit_while_waiting_for_approval(tmp_path, monkeypatch):
    path = tmp_path / "sample.py"
    path.write_text("source")

    def edit_then_approve(prompt):
        path.write_text("my new edits")
        return "yes"

    monkeypatch.setattr("builtins.input", edit_then_approve)
    assert approve_replacement(path, b"source", "fixed") == 2
    assert path.read_text() == "my new edits"


def test_cli_apply_rejects_stdin_and_json(tmp_path):
    assert main(["check", "-", "--apply"]) == 2
    assert main(["check", str(tmp_path / "sample.py"), "--apply", "--format", "json"]) == 2
