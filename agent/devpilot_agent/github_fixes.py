"""Prepare a reviewable artifact and turn an explicitly approved artifact into a fix PR."""
from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from .diff_parser import is_code_file
from .snippet import MAX_SNIPPET_CHARS, fix_code

MAX_FILES = 8
MAX_MANIFEST = 2_500_000
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")


def editable(path: str) -> bool:
    parts = path.split("/")
    return (len(path) <= 300 and not any(not p or p.startswith(".") for p in parts)
            and re.fullmatch(r"[A-Za-z0-9_./ +@()-]+", path) is not None and is_code_file(path))


def blob_id(text: str) -> str:
    raw = text.encode()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def preview(path: str, original: str, updated: str) -> str:
    # Preserve CRLF and mark missing final newlines so both are visible in the patch.
    lines = difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                 fromfile="a/" + path, tofile="b/" + path)
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                   for line in lines)


def prepare(folder, repository, branch, head, pr, repo, llm, result):
    """Only propose edits to source files with comments kept by the verifier."""
    groups = {}
    for comment in result.comments:
        if editable(comment.path):
            groups.setdefault(comment.path, []).append(comment)
    files, patches = {}, []
    for path, comments in sorted(groups.items())[:MAX_FILES]:
        source = repo.read_file(path)
        if source is None or len(source) > MAX_SNIPPET_CHARS or "\0" in source:
            continue
        updated, _, _ = fix_code(llm, source, path, result.model_copy(update={"comments": comments}))
        if updated == source or len(updated) > MAX_SNIPPET_CHARS or "\0" in updated:
            continue
        files[path] = {"blob": blob_id(source), "code": updated}
        patches.append(preview(path, source, updated))
    if not files:
        return ""
    patch = "".join(patches).encode()
    manifest = {"version": 1, "repository": repository, "branch": branch, "head": head,
                "pr": pr, "files": files, "preview_sha256": hashlib.sha256(patch).hexdigest()}
    raw = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
    if len(raw) > MAX_MANIFEST:
        raise ValueError("Fix proposal exceeds artifact size limit")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "proposal.json").write_bytes(raw)
    (folder / "preview.diff").write_bytes(patch)
    return hashlib.sha256(raw).hexdigest()


def approval_note(event_pr, head, branch, target, agent, result):
    if os.getenv("DEVPILOT_PROPOSE_FIXES") != "true" or not branch or not result.comments:
        return ""
    repository = os.environ["GITHUB_REPOSITORY"]
    if event_pr and (event_pr["head"]["repo"]["full_name"] != repository or event_pr["head"]["sha"] != head):
        return "\n\nFix proposals are available for current branches in this repository."
    try:
        digest = prepare(Path(os.environ["RUNNER_TEMP"]) / "devpilot-proposal", repository, branch, head,
                         event_pr["number"] if event_pr else None, target, agent.llm, result)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        return f"\n\nThe review completed, but DevPilot could not prepare a fix preview ({type(exc).__name__})."
    if not digest:
        return "\n\nNo automatic edit was proposed for these findings."
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        out.write("has_proposal=true\n")
    run = os.environ["GITHUB_RUN_ID"]
    url = f'{os.getenv("GITHUB_SERVER_URL", "https://github.com")}/{repository}/actions/runs/{run}'
    return (f"\n\n**Approve a fix** · Open [review run {run}]({url}), download "
            "`devpilot-proposal`, and inspect `preview.diff`. To apply those exact edits, choose "
            "**Actions → DevPilot review → Run workflow** on the default branch, select `approve`, "
            f"and enter run ID `{run}` and proposal SHA-256 `{digest}`. This opens a fix pull request.")


class ApprovalError(ValueError):
    pass


class Approver:
    def __init__(self, client, api, repository):
        self.client = client
        self.base = f"{api}/repos/{repository}"
        self.repo = repository

    def get(self, path, **kwargs):
        response = self.client.get(self.base + path, **kwargs)
        response.raise_for_status()
        return response.json()

    def post(self, path, data):
        response = self.client.post(self.base + path, json=data)
        response.raise_for_status()
        return response.json()

    def verify_run(self, selected, current):
        if not re.fullmatch(r"[1-9][0-9]{0,18}", selected):
            raise ApprovalError("Enter the review run ID from the proposal")
        review = self.get("/actions/runs/" + selected)
        approval = self.get("/actions/runs/" + current)
        if (review["repository"]["full_name"] != self.repo or review["workflow_id"] != approval["workflow_id"]
                or review["event"] not in {"pull_request_target", "pull_request", "push", "workflow_dispatch"}
                or review["status"] != "completed" or review["conclusion"] not in {"success", "failure"}):
            raise ApprovalError("Select a completed review from this repository's DevPilot workflow")

    def verify_actor(self, name):
        permission = self.get("/collaborators/" + quote(name, safe="") + "/permission")["permission"]
        if permission not in {"write", "maintain", "admin"}:
            raise ApprovalError("Only a repository writer can approve a proposal")

    def verify_head(self, manifest):
        head, branch, number = manifest["head"], manifest["branch"], manifest["pr"]
        if number is not None:
            pr = self.get(f"/pulls/{int(number)}")
            if (pr["state"] != "open" or pr["head"]["repo"]["full_name"] != self.repo
                or pr["head"]["ref"] != branch or pr["head"]["sha"] != head):
                raise ApprovalError("The reviewed pull request changed or closed. Request a new review")
        if self.get("/git/ref/heads/" + quote(branch, safe="/"))["object"]["sha"] != head:
            raise ApprovalError("The reviewed branch moved. Request a new review before approving")

    def apply(self, folder, digest, actors):
        if not DIGEST.fullmatch(digest):
            raise ApprovalError("Enter the full proposal SHA-256 displayed in the review")
        for actor in set(actors):
            self.verify_actor(actor)
        raw = (folder / "proposal.json").read_bytes()
        if len(raw) > MAX_MANIFEST or hashlib.sha256(raw).hexdigest() != digest:
            raise ApprovalError("Proposal digest does not match the reviewed artifact")
        m = json.loads(raw)
        if (m.get("version") != 1 or m.get("repository") != self.repo or not SHA.fullmatch(m["head"])
            or not m["branch"] or m["branch"].startswith("devpilot/fix-")
            or not isinstance(m["files"], dict) or not 0 < len(m["files"]) <= MAX_FILES):
            raise ApprovalError("Proposal does not match the expected repository or format")
        self.verify_head(m)
        head = m["head"]
        tree = self.get("/git/commits/" + head)["tree"]["sha"]
        changes, diffs, trees = [], [], {}
        for path, change in sorted(m["files"].items()):
            if not editable(path) or not isinstance(change["code"], str) or len(change["code"]) > MAX_SNIPPET_CHARS:
                raise ApprovalError("Unsupported file in proposal")
            subtree = tree
            for index, part in enumerate(path.split("/")):
                if subtree not in trees:
                    trees[subtree] = {e["path"]: e for e in self.get("/git/trees/" + subtree)["tree"]}
                entry = trees[subtree].get(part)
                if not entry:
                    raise ApprovalError("Reviewed file no longer exists")
                if index < len(path.split("/")) - 1 and entry["type"] != "tree":
                    raise ApprovalError("Invalid directory in proposal")
                subtree = entry["sha"]
            if (entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}
                    or entry["sha"] != change["blob"]):
                raise ApprovalError("Only the exact reviewed regular file may be changed")
            blob = self.get("/git/blobs/" + entry["sha"])
            original = base64.b64decode(blob["content"]).decode("utf-8")
            diffs.append(preview(path, original, change["code"]))
            changes.append({"path": path, "mode": entry["mode"], "type": "blob", "content": change["code"]})
        # The manifest is authenticated by the human-supplied digest. Also bind the visible
        # preview to the edits and to the downloaded file before creating any Git objects.
        patch = "".join(diffs).encode()
        if (not patch or hashlib.sha256(patch).hexdigest() != m["preview_sha256"]
                or (folder / "preview.diff").read_bytes() != patch):
            raise ApprovalError("The preview does not match the proposed edits")

        branch = "devpilot/fix-" + digest[:24]
        newtree = self.post("/git/trees", {"base_tree": tree, "tree": changes})["sha"]
        ref_path = "/git/ref/heads/" + branch
        ref = self.client.get(self.base + ref_path)
        if ref.status_code == 404:
            commit = self.post("/git/commits", {"message": "Apply approved DevPilot review fixes",
                                                "tree": newtree, "parents": [head]})
            self.verify_head(m)
            created = self.client.post(self.base + "/git/refs", json={"ref": "refs/heads/" + branch, "sha": commit["sha"]})
            if created.status_code != 422:  # a concurrent approval may have created the branch
                created.raise_for_status()
        else:
            ref.raise_for_status()
        branch_sha = self.get(ref_path)["object"]["sha"]
        existing = self.get("/git/commits/" + branch_sha)
        if existing["tree"]["sha"] != newtree or [p["sha"] for p in existing["parents"]] != [head]:
            raise ApprovalError("Fix branch has unrelated edits; refusing to reuse it")
        self.verify_head(m)
        params = {"head": self.repo.split("/")[0] + ":" + branch, "base": m["branch"], "state": "all"}
        def prior():
            pulls = self.get("/pulls", params=params)
            return next((p["html_url"] for p in pulls if p["head"].get("repo")
                         and p["head"]["repo"]["full_name"] == self.repo), None)
        url = prior()
        if url:
            return url
        body = {"head": branch, "base": m["branch"], "title": "Apply approved DevPilot review fixes",
                "body": f"Approved proposal `{digest}` for commit `{head}`."}
        created = self.client.post(self.base + "/pulls", json=body)
        if created.status_code == 422:
            url = prior()
            if url:
                return url
        created.raise_for_status()
        return created.json()["html_url"]
