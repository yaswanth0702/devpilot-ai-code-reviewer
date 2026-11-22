"""Parse unified diffs into a map of which lines changed in each file.

The verifier uses this so the agent can only comment on lines the PR actually touched
(GitHub also rejects review comments on lines outside the diff).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileDiff:
    path: str
    added_lines: set[int] = field(default_factory=set)   # lines added/modified (new numbering)
    context_lines: set[int] = field(default_factory=set)  # unchanged lines shown in hunks
    is_deleted: bool = False

    @property
    def commentable_lines(self) -> set[int]:
        return self.added_lines | self.context_lines


def parse_unified_diff(diff: str) -> dict[str, FileDiff]:
    files: dict[str, FileDiff] = {}
    current: FileDiff | None = None
    new_line = 0
    in_hunk = False

    for raw in diff.splitlines():
        if raw.startswith("diff --git"):
            current, in_hunk = None, False
            continue
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                path = target[2:] if target.startswith("b/") else target
                current = files.setdefault(path, FileDiff(path))
            in_hunk = False
            continue
        if raw.startswith("--- "):
            continue
        m = _HUNK.match(raw)
        if m:
            new_line = int(m.group(1))
            in_hunk = current is not None
            continue
        if not in_hunk or current is None:
            continue
        if raw.startswith("+"):
            current.added_lines.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            pass  # removed line: no new-file line number
        elif raw.startswith("\\"):
            pass  # "\ No newline at end of file"
        else:
            current.context_lines.add(new_line)
            new_line += 1
    return files


# ---------------------------------------------------------------- code-only filtering
CODE_EXTENSIONS = {
    ".py", ".java", ".kt", ".kts", ".scala", ".groovy", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".m", ".dart",
    ".sql", ".sh", ".bash", ".zsh", ".ps1", ".tf", ".hcl", ".yml", ".yaml", ".gradle", ".vue", ".svelte",
    ".r", ".lua", ".pl", ".ex", ".exs", ".erl", ".hs", ".clj", ".fs", ".vb",
}
CODE_FILENAMES = {"Dockerfile", "Makefile", "Jenkinsfile", "pom.xml", "build.gradle", "settings.gradle"}


def is_code_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in CODE_FILENAMES or name.startswith("Dockerfile"):
        return True
    dot = name.rfind(".")
    return dot > 0 and name[dot:].lower() in CODE_EXTENSIONS


def filter_code_diff(diff: str) -> tuple[str, list[str]]:
    """Keep only the file sections of a unified diff that touch code files.

    Returns (filtered_diff, skipped_paths)."""
    sections: list[list[str]] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git") or not sections:
            sections.append([])
        sections[-1].append(line)
    kept, skipped = [], []
    for sec in sections:
        path = None
        for line in sec:
            if line.startswith("+++ ") and line[4:].strip() != "/dev/null":
                path = line[4:].strip()
                path = path[2:] if path.startswith("b/") else path
                break
            if line.startswith("--- ") and line[4:].strip() != "/dev/null":
                p = line[4:].strip()
                path = p[2:] if p.startswith("a/") else p
        if path is None:
            continue  # binary or mode-only change
        (kept if is_code_file(path) else skipped).append((path, sec))
    return "".join("".join(sec) for _, sec in kept), [p for p, _ in skipped]
