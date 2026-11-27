"""The web review, change preview and discussion work independently with an offline model."""
from fastapi.testclient import TestClient

from devpilot_agent import app as api

CODE = 'public boolean isAdmin(String role) { return role == "admin"; }'
FIXED = 'public boolean isAdmin(String role) { return "admin".equals(role); }'


def test_preview_and_discussion_with_offline_provider(monkeypatch):
    monkeypatch.setenv("DEVPILOT_PROVIDER", "mock")
    client = TestClient(api.app)
    for original, corrected in ((CODE, FIXED), (CODE + "\r\n", FIXED + "\r\n")):
        source = {"filename": "Role.java", "code": original}
        response = client.post("/check", json=source)
        assert response.status_code == 200
        reviewed = response.json()
        assert reviewed["fixed_code"] is None
        context = {**source, "review": reviewed["review"]}
        proposal = client.post("/preview", json=context).json()
        assert proposal["fixed_code"] == corrected
        assert "-public boolean" in proposal["diff"] and "+public boolean" in proposal["diff"]
        answer = client.post("/chat", json={**context, "question": "Explain line 1."})
        assert answer.status_code == 200
        assert "Line 1 of Role.java" in answer.json()["answer"]
        assert "fixed_code" not in answer.json()
        approval_in_chat = client.post("/chat", json={**context, "question": "Approve and apply"})
        assert set(approval_in_chat.json()) == {"answer"}


def test_follow_up_includes_previous_turn_and_uses_only_answer_tool(monkeypatch):
    from devpilot_agent.agent import ReviewAgent
    from devpilot_agent.llm import LLMResponse, ScriptedLLM

    def answer(step, messages, tools):
        assert [tool.name for tool in tools] == ["answer_question"]
        assert "previous answer" in messages[0]["content"][0]["text"]
        return LLMResponse(text="Use a distinct String object to exercise value equality.")

    monkeypatch.setattr(api, "_agent", lambda: ReviewAgent(ScriptedLLM(answer)))
    context = {"code": CODE, "filename": "Role.java", "review": {"summary": "Compare strings.", "comments": []},
               "history": [{"role": "assistant", "text": "previous answer"}], "question": "How would I test it?"}
    client = TestClient(api.app)
    assert "String object" in client.post("/chat", json=context).json()["answer"]
    assert client.post("/chat", json={**context, "history": context["history"] * 9}).status_code == 422


def test_bad_input_and_missing_credentials(monkeypatch):
    client = TestClient(api.app)
    monkeypatch.setenv("DEVPILOT_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    error = client.post("/check", json={"code": CODE})
    assert error.status_code == 502 and "ANTHROPIC_API_KEY" in error.json()["detail"]
    for code in ("", "x" * 60001, "source\0bytes"):
        assert client.post("/check", json={"code": code}).status_code == 422
    assert client.post("/check", json={"code": CODE, "filename": "bad\nname"}).status_code == 422
