import base64
import hashlib
import json

import httpx
import pytest

from devpilot_agent.github_baseline import baseline
from devpilot_agent import github_fixes as fixes
from devpilot_agent.models import ReviewComment, ReviewResult
from devpilot_agent.repo import InMemoryRepo, GitHubRepo


class Git:
    """Small REST fixture with real proposal generation and branch/PR state."""
    def __init__(self):
        self.source = "return 0\n"
        self.head, self.base_tree = "a" * 40, "b" * 40
        self.new_tree, self.new_head = "c" * 40, "d" * 40
        self.ref = None
        self.pr = None
        self.writes = []
        self.permission = "write"
        self.mode = "100644"
        self.current = self.head

    def api(self, request):
        path = request.url.path.removeprefix("/repos/o/r")
        method = request.method
        payload = json.loads(request.content) if request.content else {}
        if method == "POST":
            self.writes.append((path, payload))
        def response(data, status=200):
            return httpx.Response(status, json=data)
        if path == "/collaborators/alice/permission":
            return response({"permission": self.permission})
        if path == "/pulls/7":
            return response({"state": "open", "head": {"repo": {"full_name": "o/r"}, "ref": "work", "sha": self.current}})
        if path == "/git/ref/heads/work":
            return response({"object": {"sha": self.current}})
        if path == "/git/commits/" + self.head:
            return response({"tree": {"sha": self.base_tree}})
        if path == "/git/trees/" + self.base_tree:
            return response({"tree": [{"path": p, "sha": fixes.blob_id(self.source), "type": "blob", "mode": self.mode}
                                      for p in ["a.py", "z.py"]]})
        if path == "/git/blobs/" + fixes.blob_id(self.source):
            return response({"content": base64.b64encode(self.source.encode()).decode()})
        if path == "/git/trees":
            assert [e["path"] for e in payload["tree"]] == ["a.py", "z.py"]
            return response({"sha": self.new_tree})
        if path.startswith("/git/ref/heads/devpilot/fix-"):
            return response({"object": {"sha": self.ref}}) if self.ref else response({}, 404)
        if path == "/git/commits":
            return response({"sha": self.new_head})
        if path == "/git/refs":
            assert payload["ref"].startswith("refs/heads/devpilot/fix-")
            self.ref = payload["sha"]
            return response({})
        if path == "/git/commits/" + self.new_head:
            return response({"tree": {"sha": self.new_tree}, "parents": [{"sha": self.head}]})
        if path == "/pulls" and method == "POST":
            assert payload["base"] == "work"
            self.pr = {"head": {"repo": {"full_name": "o/r"}}, "html_url": "https://example.test/pulls/8"}
            return response(self.pr)
        if path == "/pulls":
            return response([self.pr] if self.pr else [])
        raise AssertionError((method, path))


@pytest.fixture
def artifact(tmp_path, monkeypatch):
    gh = Git()
    repo = InMemoryRepo("", {"z.py": gh.source, "a.py": gh.source})
    comments = [ReviewComment(path=p, line=1, severity="major", category="bug", body="Wrong result") for p in repo._files]
    monkeypatch.setattr(fixes, "fix_code", lambda *a: ("return 1\n", "", ""))
    digest = fixes.prepare(tmp_path, "o/r", "work", gh.head, 7, repo, None, ReviewResult(summary="", comments=comments))
    client = httpx.Client(transport=httpx.MockTransport(gh.api))
    return gh, fixes.Approver(client, "https://api", "o/r"), tmp_path, digest


def test_exact_preview_approved_once_and_retry_opens_same_pr(artifact):
    gh, service, folder, digest = artifact
    assert gh.writes == []
    assert service.apply(folder, digest, ["alice"]).endswith("/8")
    assert service.apply(folder, digest, ["alice"]).endswith("/8")
    assert sum(p == "/pulls" for p, _ in gh.writes) == 1
    assert sum(p == "/git/refs" for p, _ in gh.writes) == 1


@pytest.mark.parametrize("case", ["actor", "head", "digest", "preview", "symlink", "forged", "expired"])
def test_rejects_unapproved_or_stale_content_before_writes(artifact, case):
    gh, service, folder, digest = artifact
    if case == "actor":
        gh.permission = "read"
    if case == "head":
        gh.current = "e" * 40
    if case == "digest":
        digest = "0" * 64
    if case == "preview":
        (folder / "preview.diff").write_text("another patch")
    if case == "symlink":
        gh.mode = "120000"
    if case == "expired":
        (folder / "proposal.json").unlink()
    if case == "forged":
        p = folder / "proposal.json"
        data = json.loads(p.read_bytes())
        data["repository"] = "other/repo"
        p.write_text(json.dumps(data))
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises((fixes.ApprovalError, FileNotFoundError)):
        service.apply(folder, digest, ["alice"])
    assert gh.writes == []


def test_baseline_uses_snapshot_and_reports_coverage():
    gh = Git()
    client = httpx.Client(transport=httpx.MockTransport(gh.api))
    repo, note = baseline(client, "https://api/repos/o/r", gh.head)
    assert set(repo.list_files()) == {"a.py", "z.py"} and "2 of 2" in note


def test_remote_reads_pinned_diff_and_declines_traversal_and_symlinks():
    routes = []
    def respond(r):
        url = r.url.path
        routes.append(url)
        if url.endswith("/pulls/5"):
            return httpx.Response(200, json={"head": {"sha": "abc"}, "base": {"sha": "def"}})
        if url.endswith("def...abc"):
            return httpx.Response(200, text="diff --git a/x b/x\nnew file mode 120000\n+++ b/x\n@@ -0,0 +1 @@\n+target\n")
        raise AssertionError(url)
    repo = GitHubRepo("o", "r", 5, "test", httpx.Client(transport=httpx.MockTransport(respond)))
    assert repo.read_file("x") is None and repo.read_file("../.env") is None
    assert len(routes) == 2


@pytest.mark.parametrize("path", [".github/workflows/check.yml", "p/../test.py", "x#1.py", "x?y.py", "../x.py", "k/.env"])
def test_unsupported_edits_are_excluded(path):
    assert not fixes.editable(path)


def test_installation_merge_detected_from_commits_without_file_lists(monkeypatch):
    from devpilot_agent import github_action as action
    gh = Git()
    def api(request):
        if "/contents/" in request.url.path:
            return httpx.Response(404 if request.url.params["ref"] == "0aa" else 200, json={})
        if "/comments" in request.url.path:
            assert "Baseline reviewed 2 of 2" in json.loads(request.content)["body"]
            return httpx.Response(201)
        return gh.api(request)
    monkeypatch.setattr(action, "_api_client", lambda _: httpx.Client(transport=httpx.MockTransport(api)))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("DEVPILOT_PROVIDER", "mock")
    assert action.review_push({"ref": "refs/heads/trunk", "repository": {"default_branch": "trunk"},
                               "before": "0aa", "after": gh.head, "commits": [{"id": gh.head}]}, "t") == 0


@pytest.mark.parametrize("wrong", ["workflow", "repository", "event", "status", "invalid_id"])
def test_approval_checks_originating_run(wrong):
    run = {"repository": {"full_name": "o/r"}, "workflow_id": 3, "event": "push", "status": "completed", "conclusion": "success"}
    selected = dict(run)
    if wrong == "workflow":
        selected["workflow_id"] = 4
    if wrong == "repository":
        selected["repository"] = {"full_name": "someone/other"}
    if wrong == "event":
        selected["event"] = "issue_comment"
    if wrong == "status":
        selected["status"] = "in_progress"
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=selected if r.url.path.endswith("/1") else run)))
    service = fixes.Approver(client, "https://api", "o/r")
    with pytest.raises(fixes.ApprovalError):
        service.verify_run("/1" if wrong == "invalid_id" else "1", "2")


def test_action_dispatch_applies_selected_patch_without_model(artifact, monkeypatch):
    from devpilot_agent import github_action as action
    gh, _, folder, digest = artifact
    approved = folder / "devpilot-approved"
    approved.mkdir()
    for filename in ["preview.diff", "proposal.json"]:
        (folder / filename).rename(approved / filename)
    event = folder / "event.json"
    event.write_text(json.dumps({"inputs": {"operation": "approve", "review_run": "12", "proposal_digest": digest},
                                 "repository": {"default_branch": "trunk"}}))
    for key, value in {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_EVENT_PATH": str(event),
                       "GITHUB_REF": "refs/heads/trunk", "GITHUB_TOKEN": "test", "GITHUB_REPOSITORY": "o/r",
                       "GITHUB_RUN_ID": "13", "GITHUB_ACTOR": "alice", "GITHUB_TRIGGERING_ACTOR": "alice",
                       "RUNNER_TEMP": str(folder)}.items():
        monkeypatch.setenv(key, value)
    def handler(request):
        if "/actions/runs/" in request.url.path:
            return httpx.Response(200, json={"event": "push", "repository": {"full_name": "o/r"}, "workflow_id": 3,
                                             "status": "completed", "conclusion": "success"})
        return gh.api(request)
    monkeypatch.setattr(action, "_api_client", lambda _: httpx.Client(transport=httpx.MockTransport(handler)))
    assert action.main() == 0 and gh.pr is not None
