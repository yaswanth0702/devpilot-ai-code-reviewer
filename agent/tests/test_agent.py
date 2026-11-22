from devpilot_agent.agent import ReviewAgent
from devpilot_agent.llm import LLMResponse, ScriptedLLM, ToolCall
from devpilot_agent.mock_provider import mock_reviewer
from devpilot_agent.repo import CodeSearchIndex, InMemoryRepo


def test_tool_loop_then_submit(sample_diff, sample_files):
    def script(i, messages, tools):
        if i == 0:
            return LLMResponse(tool_calls=[ToolCall("t1", "read_file", {"path": "src/UserService.java", "start_line": 10, "end_line": 15})],
                               input_tokens=100, output_tokens=10)
        if i == 1:
            # the tool output from step 0 must have been fed back
            last = messages[-1]["content"][0]
            assert last["type"] == "tool_result" and 'name == "admin"' in last["content"]
            return LLMResponse(tool_calls=[ToolCall("t2", "search_code", {"query": "byName"})])
        return LLMResponse(tool_calls=[ToolCall("t3", "submit_review", {
            "summary": "Adds an admin guard.",
            "comments": [
                {"path": "src/UserService.java", "line": 11, "severity": "major", "category": "bug",
                 "body": "== compares references; use equals().", "confidence": 0.9},
                {"path": "src/Ghost.java", "line": 1, "severity": "major", "category": "bug",
                 "body": "hallucinated file comment here", "confidence": 0.9},
                {"path": "src/UserService.java", "line": "not-a-number"},  # malformed -> ignored
            ],
        })])

    llm = ScriptedLLM(script)
    result = ReviewAgent(llm).review(InMemoryRepo(sample_diff, sample_files))
    assert result.steps == 3 and result.tool_calls == 3
    assert [c.line for c in result.comments] == [11]
    assert [d.reason for d in result.dropped] == ["file_not_in_diff"]
    assert result.input_tokens == 100


def test_step_budget_forces_submit(sample_diff, sample_files):
    def script(i, messages, tools):
        names = [t.name for t in tools]
        if names == ["submit_review"]:
            return LLMResponse(tool_calls=[ToolCall("s", "submit_review", {"summary": "done", "comments": []})])
        return LLMResponse(tool_calls=[ToolCall(f"r{i}", "search_code", {"query": "repo"})])

    result = ReviewAgent(ScriptedLLM(script), max_steps=3).review(InMemoryRepo(sample_diff, sample_files))
    assert result.steps == 3 and result.summary == "done"


def test_messages_alternate_roles(sample_diff, sample_files):
    def script(i, messages, tools):
        roles = [m["role"] for m in messages]
        assert all(a != b for a, b in zip(roles, roles[1:])), roles
        if i < 2:
            return LLMResponse(text="thinking")  # no tool call -> agent nudges
        return LLMResponse(tool_calls=[ToolCall("s", "submit_review", {"summary": "ok", "comments": []})])

    ReviewAgent(ScriptedLLM(script), max_steps=4).review(InMemoryRepo(sample_diff, sample_files))


def test_unknown_tool_is_reported_not_crash(sample_diff, sample_files):
    def script(i, messages, tools):
        if i == 0:
            return LLMResponse(tool_calls=[ToolCall("x", "rm_rf", {})])
        assert messages[-1]["content"][0]["is_error"] is True
        return LLMResponse(tool_calls=[ToolCall("s", "submit_review", {"summary": "ok", "comments": []})])

    ReviewAgent(ScriptedLLM(script)).review(InMemoryRepo(sample_diff, sample_files))


def test_mock_provider_end_to_end(sample_diff, sample_files):
    result = ReviewAgent(mock_reviewer()).review(InMemoryRepo(sample_diff, sample_files))
    assert result.tool_calls == 3
    assert [(c.path, c.line, c.category.value) for c in result.comments] == [("src/UserService.java", 11, "bug")]


def test_bm25_finds_definition(sample_files):
    hits = CodeSearchIndex(sample_files).search("UserRepository byName")
    assert hits[0][0] == "src/UserRepository.java"
