"""Tools the review agent can call. Each returns a string fed back to the model."""
from __future__ import annotations

from typing import Any

from .llm import ToolSpec
from .models import Category, Severity
from .repo import CodeSearchIndex, Repo

MAX_READ_LINES = 200

READ_FILE = ToolSpec(
    name="read_file",
    description=(
        "Read lines from a file at the PR's head commit. Use it to see full context around a change "
        "or to inspect callers/definitions. Lines are returned with numbers."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
    },
)

SEARCH_CODE = ToolSpec(
    name="search_code",
    description="Keyword (BM25) search across the repository. Returns the best-matching file regions.",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}, "k": {"type": "integer", "default": 5}},
        "required": ["query"],
    },
)

SUBMIT_REVIEW = ToolSpec(
    name="submit_review",
    description=(
        "Submit the final review. Call exactly once when done. Only include real, specific problems "
        "on changed lines; do not comment on style the linter would catch. Empty comments is fine."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "2-4 sentence overview of the PR and its risk."},
            "comments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "line": {"type": "integer", "description": "line number in the NEW file"},
                        "severity": {"type": "string", "enum": [s.value for s in Severity]},
                        "category": {"type": "string", "enum": [c.value for c in Category]},
                        "body": {"type": "string", "description": "What is wrong and why it matters."},
                        "suggestion": {"type": "string", "description": "Concrete fix (code if short)."},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["path", "line", "severity", "category", "body", "confidence"],
                },
            },
        },
        "required": ["summary", "comments"],
    },
)

ALL_TOOLS = [READ_FILE, SEARCH_CODE, SUBMIT_REVIEW]


class ToolExecutor:
    def __init__(self, repo: Repo):
        self.repo = repo
        self._index: CodeSearchIndex | None = None

    @property
    def index(self) -> CodeSearchIndex:
        if self._index is None:
            files = {p: t for p in self.repo.list_files() if (t := self.repo.read_file(p)) is not None}
            self._index = CodeSearchIndex(files)
        return self._index

    def run(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Returns (output, is_error)."""
        try:
            if name == "read_file":
                return self._read_file(**args), False
            if name == "search_code":
                return self._search(**args), False
            return f"unknown tool: {name}", True
        except TypeError as e:
            return f"bad arguments for {name}: {e}", True

    def _read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        text = self.repo.read_file(path)
        if text is None:
            return f"file not found: {path}"
        lines = text.splitlines()
        start = max(1, start_line)
        end = min(len(lines), end_line or start + MAX_READ_LINES - 1, start + MAX_READ_LINES - 1)
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        more = f"\n... ({len(lines) - end} more lines)" if end < len(lines) else ""
        return f"{path} (lines {start}-{end} of {len(lines)})\n{body}{more}"

    def _search(self, query: str, k: int = 5) -> str:
        hits = self.index.search(query, k=min(max(k, 1), 10))
        if not hits:
            return "no matches"
        return "\n".join(f"{p}:{s}-{e} (score {sc:.2f})" for p, s, e, sc in hits)
