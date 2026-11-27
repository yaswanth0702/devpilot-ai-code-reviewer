"""Offer the review workflow to repositories covered by a signed GitHub webhook."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import quote

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

router = APIRouter()
SOURCE = "yaswanth0702/devpilot-ai-code-reviewer"
WORKFLOW = ".github/workflows/devpilot-review.yml"
BRANCH = "devpilot/setup-review"
MAX_DELIVERY = 25 * 1024 * 1024


def _token(client: httpx.Client, event: dict) -> str:
    app_id = os.getenv("DEVPILOT_ONBOARDING_APP_ID")
    key = os.getenv("DEVPILOT_ONBOARDING_PRIVATE_KEY")
    if app_id or key:
        installation = (event.get("installation") or {}).get("id")
        repo_id = event["repository"].get("id")
        if not app_id or not key or not isinstance(installation, int) or not isinstance(repo_id, int):
            raise HTTPException(503, "Check GitHub App installation and onboarding credentials.")
        now = int(time.time())
        try:
            signed = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id},
                                key.replace("\\n", "\n"), algorithm="RS256")
        except (ValueError, jwt.PyJWTError) as exc:
            raise HTTPException(503, "Check the onboarding app's private key.") from exc
        response = client.post(f"/app/installations/{installation}/access_tokens",
                               headers={"Authorization": f"Bearer {signed}"}, json={"repository_ids": [repo_id]})
        response.raise_for_status()
        return response.json()["token"]
    token = os.getenv("DEVPILOT_ONBOARDING_TOKEN")
    if not token:
        raise HTTPException(503, "Configure onboarding credentials.")
    return token


def _expected_workflow(client: httpx.Client, ref: str) -> str:
    # The template and every DevPilot action reference come from one operator-selected release.
    response = client.get(f"/repos/{SOURCE}/contents/examples/devpilot-review.yml", params={"ref": ref})
    response.raise_for_status()
    content = base64.b64decode(response.json()["content"]).decode("utf-8")
    return content.replace(f"{SOURCE}@main", f"{SOURCE}@{ref}")


def _find_pull(client: httpx.Client, repo: str, head: str, base: str) -> dict | None:
    response = client.get(f"{repo}/pulls", params={"state": "all", "head": head, "base": base, "per_page": 1})
    response.raise_for_status()
    return next(iter(response.json()), None)


def _existing_pull(pull: dict) -> dict:
    return {"status": "open" if pull["state"] == "open" else "closed", "pull_request": pull["html_url"]}


def _onboard(client: httpx.Client, event: dict, release: str) -> dict:
    data = event["repository"]
    owner, name, base = data["owner"]["login"], data["name"], data["default_branch"]
    repo = f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
    client.headers["Authorization"] = f"Bearer {_token(client, event)}"
    target = client.get(f"{repo}/git/ref/heads/{quote(base, safe='/')}")
    if target.status_code in {404, 409}:
        return {"status": "waiting_for_default_branch"}
    target.raise_for_status()
    sha = target.json()["object"]["sha"]
    installed = client.get(f"{repo}/contents/{WORKFLOW}", params={"ref": sha})
    if installed.is_success:
        return {"status": "already_configured"}
    if installed.status_code != 404:
        installed.raise_for_status()

    head = f"{owner}:{BRANCH}"
    prior = _find_pull(client, repo, head, base)
    if prior:
        return _existing_pull(prior)
    workflow = _expected_workflow(client, release)
    # Build the full proposal before publishing its branch. Failures cannot leave a half-written branch.
    commit = client.get(f"{repo}/git/commits/{sha}")
    commit.raise_for_status()
    tree = client.post(f"{repo}/git/trees", json={"base_tree": commit.json()["tree"]["sha"], "tree": [
        {"path": WORKFLOW, "mode": "100644", "type": "blob", "content": workflow}
    ]})
    tree.raise_for_status()
    proposal = client.post(f"{repo}/git/commits", json={
        "message": "Add DevPilot review workflow", "tree": tree.json()["sha"], "parents": [sha]
    })
    proposal.raise_for_status()
    branch = client.post(f"{repo}/git/refs", json={"ref": f"refs/heads/{BRANCH}", "sha": proposal.json()["sha"]})
    if branch.status_code == 422:
        # A redelivery can encounter our branch after the first attempt stopped before creating a PR.
        compare = client.get(f"{repo}/compare/{quote(sha, safe='')}...{quote(BRANCH, safe='')}")
        compare.raise_for_status()
        files = compare.json().get("files", [])
        content = workflow.encode()
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if len(files) != 1 or (files[0].get("filename"), files[0].get("status"), files[0].get("sha")) != (WORKFLOW, "added", blob):
            return {"status": "setup_branch_conflict"}
    else:
        branch.raise_for_status()
    pull = client.post(f"{repo}/pulls", json={
        "title": "Set up DevPilot code review", "head": BRANCH, "base": base,
        "body": "Review this workflow and configure the provider secret it references. "
                "Merge this PR to enable DevPilot reviews and approval-based fix proposals."
    })
    if pull.status_code == 422:
        concurrent = _find_pull(client, repo, head, base)
        if concurrent:
            return _existing_pull(concurrent)
    pull.raise_for_status()
    return _existing_pull(pull.json())


def _handle(event_type: str, event: dict, owner: str, release: str) -> dict:
    if event_type == "ping":
        return {"status": "pong"}
    repo = event.get("repository") or {}
    repo_owner = (repo.get("owner") or {}).get("login", "")
    base = repo.get("default_branch")
    if repo_owner.casefold() != owner.casefold() or not base or not repo.get("name"):
        return {"status": "ignored"}
    if repo.get("archived") or repo.get("disabled") or repo.get("fork") or base == BRANCH:
        return {"status": "ignored"}
    created = event_type == "repository" and event.get("action") == "created"
    pushed = event_type == "push" and event.get("ref") == f"refs/heads/{base}" and not event.get("deleted")
    if not created and not pushed:
        return {"status": "ignored"}
    if not re.fullmatch(r"[0-9a-fA-F]{40}", release):
        raise HTTPException(503, "Configure a full DevPilot release commit SHA.")
    try:
        with httpx.Client(base_url="https://api.github.com", timeout=8,
                          headers={"Accept": "application/vnd.github+json",
                                   "X-GitHub-Api-Version": "2022-11-28"}) as client:
            return _onboard(client, event, release)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"GitHub onboarding request returned {exc.response.status_code}.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "GitHub onboarding request did not finish.") from exc


@router.post("/onboarding/github")
async def onboarding(request: Request) -> dict:
    secret = os.getenv("DEVPILOT_ONBOARDING_SECRET")
    owner = os.getenv("DEVPILOT_ONBOARDING_OWNER")
    if not secret or not owner:
        raise HTTPException(404, "Onboarding is disabled.")
    signature = request.headers.get("x-hub-signature-256", "")
    if not re.fullmatch(r"sha256=[a-f0-9]{64}", signature):
        raise HTTPException(401, "Invalid signature.")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_DELIVERY:
            raise HTTPException(413, "Delivery exceeds the GitHub payload limit.")
        body.extend(chunk)
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, "sha256=" + digest):
        raise HTTPException(401, "Invalid signature.")
    try:
        event = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(400, "Invalid webhook JSON.") from exc
    if not isinstance(event, dict):
        raise HTTPException(400, "Expected a webhook object.")
    return await run_in_threadpool(_handle, request.headers.get("x-github-event", ""), event, owner,
                                   os.getenv("DEVPILOT_ONBOARDING_REF", ""))
