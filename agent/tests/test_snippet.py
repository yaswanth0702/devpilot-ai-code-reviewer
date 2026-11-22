"""Reviewing pasted code / a single file, and producing a fixed version."""
import json

from fastapi.testclient import TestClient

from devpilot_agent import app as app_module
from devpilot_agent.agent import ReviewAgent
from devpilot_agent.cli import main
from devpilot_agent.diff_parser import parse_unified_diff
from devpilot_agent.llm import LLMResponse, ScriptedLLM, ToolCall
from devpilot_agent.snippet import fix_code, review_snippet, snippet_diff

CODE = 'def get(conn, uid):\n    return conn.execute("SELECT * FROM t WHERE id=" + uid)\n'
FIXED = 'def get(conn, uid):\n    return conn.execute("SELECT * FROM t WHERE id=?", (uid,))\n'


def test_snippet_diff_makes_every_line_reviewable():
    files = parse_unified_diff(snippet_diff(CODE, "db.py"))
    assert files["db.py"].added_lines == {1, 2}


def _scripted():
    def script(i, messages, tools):
        names = {t.name for t in tools}
        if names == {"submit_fixed_code"}:
            prompt = messages[0]["content"][0]["text"]
            assert "line 2 [critical/security]" in prompt and "parameterized" in prompt
            return LLMResponse(tool_calls=[ToolCall("f", "submit_fixed_code", {"code": FIXED, "notes": "Parameterized the query"})])
        return LLMResponse(tool_calls=[ToolCall("s", "submit_review", {"summary": "SQL injection.", "comments": [
            {"path": "db.py", "line": 2, "severity": "critical", "category": "security",
             "body": "String concatenation in SQL allows injection.", "suggestion": "Use a parameterized query.", "confidence": 0.95}]})])
    return ScriptedLLM(script)


def test_review_and_fix():
    llm = _scripted()
    result = review_snippet(ReviewAgent(llm), CODE, "db.py")
    assert [(c.line, c.category.value) for c in result.comments] == [(2, "security")]
    fixed, diff, notes = fix_code(llm, CODE, "db.py", result)
    assert fixed == FIXED and notes == "Parameterized the query"
    assert '-    return conn.execute("SELECT * FROM t WHERE id=" + uid)' in diff
    assert '+    return conn.execute("SELECT * FROM t WHERE id=?", (uid,))' in diff


def test_fix_skipped_when_no_issues():
    result = review_snippet(ReviewAgent(ScriptedLLM(lambda i, m, t: LLMResponse(tool_calls=[
        ToolCall("s", "submit_review", {"summary": "ok", "comments": []})]))), CODE, "db.py")
    assert fix_code(None, CODE, "db.py", result) == (CODE, "", "No issues to fix.")


def test_check_endpoint_and_page(monkeypatch):
    monkeypatch.setenv("DEVPILOT_PROVIDER", "mock")
    client = TestClient(app_module.app)
    assert "Paste your code" in client.get("/").text
    r = client.post("/check", json={"code": CODE, "filename": "db.py", "fix": True})
    assert r.status_code == 200
    body = r.json()
    assert body["review"]["comments"][0]["category"] == "security"
    assert body["fixed_code"] is not None
    assert client.post("/check", json={"code": "   "}).status_code == 422


def test_cli_check_file_with_fix(tmp_path, capsys):
    f = tmp_path / "db.py"
    f.write_text(CODE)
    assert main(["check", str(f), "--provider", "mock", "--format", "json", "--fix"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["comments"][0]["line"] == 2 and "fixed_code" in out
