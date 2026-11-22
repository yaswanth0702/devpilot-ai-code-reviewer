import json
import subprocess

from fastapi.testclient import TestClient

from devpilot_agent import app as app_module
from devpilot_agent.cli import main


def test_review_endpoint_with_mock(monkeypatch, sample_diff, sample_files):
    monkeypatch.setenv("DEVPILOT_PROVIDER", "mock")
    client = TestClient(app_module.app)
    assert client.get("/health").json()["status"] == "ok"
    r = client.post("/review", json={"diff": sample_diff, "files": sample_files})
    assert r.status_code == 200
    body = r.json()
    assert body["comments"][0]["line"] == 11
    assert client.get("/metrics").json()["reviews_total"] >= 1


def test_review_endpoint_validates_input(monkeypatch):
    monkeypatch.setenv("DEVPILOT_PROVIDER", "mock")
    r = TestClient(app_module.app).post("/review", json={})
    assert r.status_code == 422


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_cli_local_mode(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "db.py").write_text("def get(conn, uid):\n    return conn.execute('SELECT 1')\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    (tmp_path / "db.py").write_text(
        "def get(conn, uid):\n    return conn.execute(\"SELECT * FROM users WHERE id=\" + uid)\n"
    )

    code = main(["review", str(tmp_path), "--provider", "mock", "--format", "json", "--fail-on", "critical"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1  # critical SQL injection found -> non-zero exit for hooks/CI
    assert out["comments"][0]["category"] == "security" and out["comments"][0]["line"] == 2


def test_cli_no_changes(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    assert main(["review", str(tmp_path), "--provider", "mock"]) == 0
    assert "No changes" in capsys.readouterr().out
