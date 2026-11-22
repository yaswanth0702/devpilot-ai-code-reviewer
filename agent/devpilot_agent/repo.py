"""Repository access: the agent's view of the code under review.

`InMemoryRepo` is used for local runs, tests and evals; `GitHubRepo` fetches a real PR.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Protocol

import httpx

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


class Repo(Protocol):
    def diff(self) -> str: ...
    def read_file(self, path: str) -> str | None: ...
    def list_files(self) -> list[str]: ...


class InMemoryRepo:
    def __init__(self, diff: str, files: dict[str, str]):
        self._diff = diff
        self._files = files

    def diff(self) -> str:
        return self._diff

    def read_file(self, path: str) -> str | None:
        return self._files.get(path)

    def list_files(self) -> list[str]:
        return sorted(self._files)


class GitHubRepo:
    """Reads a PR's diff and the head-commit version of its files via the GitHub REST API."""

    API = os.getenv("GITHUB_API_URL", "https://api.github.com")

    def __init__(self, owner: str, repo: str, pr_number: int, token: str, client: httpx.Client | None = None):
        self.owner, self.repo, self.pr_number = owner, repo, pr_number
        self._client = client or httpx.Client(timeout=30)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._cache: dict[str, str | None] = {}
        pr = self._get(f"/repos/{owner}/{repo}/pulls/{pr_number}").json()
        self.head_sha: str = pr["head"]["sha"]
        self._diff: str | None = None
        self._changed: list[str] | None = None

    def _get(self, path: str, accept: str | None = None) -> httpx.Response:
        headers = dict(self._headers)
        if accept:
            headers["Accept"] = accept
        resp = self._client.get(self.API + path, headers=headers)
        resp.raise_for_status()
        return resp

    def diff(self) -> str:
        if self._diff is None:
            self._diff = self._get(
                f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}",
                accept="application/vnd.github.diff",
            ).text
        return self._diff

    def read_file(self, path: str) -> str | None:
        if path not in self._cache:
            try:
                self._cache[path] = self._get(
                    f"/repos/{self.owner}/{self.repo}/contents/{path}?ref={self.head_sha}",
                    accept="application/vnd.github.raw+json",
                ).text
            except httpx.HTTPStatusError:
                self._cache[path] = None
        return self._cache[path]

    def list_files(self) -> list[str]:
        if self._changed is None:
            files = self._get(f"/repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/files?per_page=100").json()
            self._changed = [f["filename"] for f in files]
        return self._changed


class CodeSearchIndex:
    """BM25 index over files, chunked into line windows. Lets the agent find related code
    (callers, definitions) that isn't in the diff."""

    def __init__(self, files: dict[str, str], window: int = 30, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.chunks: list[tuple[str, int, int, Counter]] = []
        for path, text in files.items():
            lines = text.splitlines()
            for start in range(0, max(len(lines), 1), window):
                chunk = lines[start : start + window]
                tf = Counter(t.lower() for t in _TOKEN.findall("\n".join(chunk)))
                self.chunks.append((path, start + 1, start + len(chunk), tf))
        n = len(self.chunks) or 1
        self.avgdl = sum(sum(c[3].values()) for c in self.chunks) / n
        df: Counter = Counter()
        for c in self.chunks:
            df.update(c[3].keys())
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int = 5) -> list[tuple[str, int, int, float]]:
        terms = [t.lower() for t in _TOKEN.findall(query)]
        scored = []
        for path, start, end, tf in self.chunks:
            dl = sum(tf.values()) or 1
            s = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if s > 0:
                scored.append((path, start, end, s))
        scored.sort(key=lambda x: -x[3])
        return scored[:k]


class LocalGitRepo:
    """Local mode: review uncommitted changes, staged changes, or a branch vs. a base branch."""

    def __init__(self, root: str = ".", base: str | None = None, staged: bool = False):
        import pathlib
        import subprocess

        self._sp = subprocess
        self.root = pathlib.Path(root).resolve()
        top = self._git("rev-parse", "--show-toplevel").strip()
        self.root = pathlib.Path(top)
        args = ["diff", "--no-color", "--unified=3"]
        if staged:
            args.append("--cached")
        elif base:
            args.append(f"{base}...HEAD")
        self._diff = self._git(*args)
        self._files = [f for f in self._git("ls-files").splitlines() if f]

    def _git(self, *args: str) -> str:
        return self._sp.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def diff(self) -> str:
        return self._diff

    def read_file(self, path: str) -> str | None:
        p = (self.root / path).resolve()
        if self.root not in p.parents or not p.is_file():
            return None  # never read outside the repo
        try:
            return p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

    def list_files(self) -> list[str]:
        return self._files
