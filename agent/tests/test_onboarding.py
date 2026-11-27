import base64
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from devpilot_agent.app import app
from devpilot_agent import onboarding as ob


SHA = "a" * 40
REPO = "/repos/example/widget"
EVENT = {"action": "created", "repository": {"id": 7, "owner": {"login": "example"},
                                          "name": "widget", "default_branch": "trunk"}}
TEMPLATE = f"uses: {ob.SOURCE}@main\n"
HEAD = f"{REPO}/git/ref/heads/trunk"


def test_signed_events_and_scope(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.delenv("DEVPILOT_ONBOARDING_SECRET", raising=False)
        assert client.post("/onboarding/github").status_code == 404
        monkeypatch.setenv("DEVPILOT_ONBOARDING_OWNER", "another-owner")
        monkeypatch.setenv("DEVPILOT_ONBOARDING_SECRET", "test-secret")
        body = json.dumps(EVENT).encode()
        headers = {"X-GitHub-Event": "repository", "X-Hub-Signature-256": "sha256=" + "0" * 64}
        assert client.post("/onboarding/github", content=body, headers=headers).status_code == 401
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        assert client.post("/onboarding/github", content=body, headers=headers).json() == {"status": "ignored"}
        headers["X-GitHub-Event"] = "ping"
        assert client.post("/onboarding/github", content=body, headers=headers).json() == {"status": "pong"}


@pytest.mark.parametrize("mode,expected", [
    ("empty", "waiting_for_default_branch"), ("installed", "already_configured"), ("new", "open"),
    ("redelivery", "open"), ("closed", "closed"), ("conflict", "setup_branch_conflict"),
])
def test_setup_with_mock_github(monkeypatch, mode, expected):
    monkeypatch.setenv("DEVPILOT_ONBOARDING_TOKEN", "test-token")
    monkeypatch.delenv("DEVPILOT_ONBOARDING_APP_ID", raising=False)
    monkeypatch.delenv("DEVPILOT_ONBOARDING_PRIVATE_KEY", raising=False)
    calls = []

    def github(req):
        path = req.url.path
        calls.append((req.method, path))
        assert req.headers["Authorization"] == "Bearer test-token"
        response, status = {}, 200
        if path == HEAD:
            response = {"object": {"sha": SHA}}
            status = 409 if mode == "empty" else 200
        elif path == f"{REPO}/contents/{ob.WORKFLOW}":
            status = 200 if mode == "installed" else 404
        elif path == f"{REPO}/pulls" and req.method == "GET":
            response = [{"state": "closed", "html_url": "pr-url"}] if mode == "closed" else []
        elif path.endswith("/contents/examples/devpilot-review.yml"):
            assert req.url.params["ref"] == SHA
            response = {"content": base64.b64encode(TEMPLATE.encode()).decode()}
        elif path == f"{REPO}/git/commits/{SHA}":
            response = {"tree": {"sha": "base-tree"}}
        elif path == f"{REPO}/git/trees":
            data = json.loads(req.content)
            assert data["base_tree"] == "base-tree"
            assert data["tree"] == [{"path": ob.WORKFLOW, "mode": "100644", "type": "blob",
                                     "content": f"uses: {ob.SOURCE}@{SHA}\n"}]
            response = {"sha": "proposal-tree"}
        elif path == f"{REPO}/git/commits":
            assert json.loads(req.content)["parents"] == [SHA]
            response = {"sha": "proposal-commit"}
        elif path == f"{REPO}/git/refs":
            assert json.loads(req.content) == {"ref": f"refs/heads/{ob.BRANCH}", "sha": "proposal-commit"}
            status = 422 if mode in {"conflict", "redelivery"} else 201
        elif "/compare/" in path:
            content = TEMPLATE.replace("main", SHA).encode()
            blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
            response = {"files": [{"filename": ob.WORKFLOW, "status": "added",
                                   "sha": blob if mode == "redelivery" else "different"}]}
        elif path == f"{REPO}/pulls" and req.method == "POST":
            assert json.loads(req.content)["base"] == "trunk"
            response, status = {"state": "open", "html_url": "pr-url"}, 201
        else:
            pytest.fail(f"Unexpected {req.method} {path}")
        return httpx.Response(status, json=response)

    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(github)) as client:
        assert ob._onboard(client, EVENT, SHA)["status"] == expected
    assert (("POST", f"{REPO}/pulls") in calls) == (mode in {"new", "redelivery"})


def test_first_default_push_retries_empty_repository(monkeypatch):
    monkeypatch.setattr(ob, "_onboard", lambda client, event, release: {"status": "handled"})
    push = {**EVENT, "ref": "refs/heads/trunk"}
    assert ob._handle("push", push, "example", SHA)["status"] == "handled"
    assert ob._handle("push", {**push, "ref": "refs/heads/topic"}, "example", SHA)["status"] == "ignored"
    assert ob._handle("push", {**push, "deleted": True}, "example", SHA)["status"] == "ignored"


def test_installation_auth_limits_token_to_delivering_repository(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import jwt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv("DEVPILOT_ONBOARDING_APP_ID", "123")
    monkeypatch.setenv("DEVPILOT_ONBOARDING_PRIVATE_KEY", pem)
    monkeypatch.setenv("DEVPILOT_ONBOARDING_TOKEN", "unused")

    def github(req):
        assert req.url.path == "/app/installations/21/access_tokens"
        assert json.loads(req.content) == {"repository_ids": [7]}
        token = req.headers["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, key.public_key(), algorithms=["RS256"], issuer="123")
        assert claims["exp"] - claims["iat"] <= 600
        return httpx.Response(201, json={"token": "installation-token"})

    with httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(github)) as client:
        event = {**EVENT, "installation": {"id": 21}}
        assert ob._token(client, event) == "installation-token"
