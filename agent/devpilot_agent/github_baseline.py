"""Bounded first review for a repository that already contains code when installed."""
from __future__ import annotations

import base64

from .github_fixes import editable
from .repo import InMemoryRepo
from .snippet import snippet_diff


def baseline(client, base, head):
    def get(path, **kwargs):
        r = client.get(base + path, **kwargs)
        r.raise_for_status()
        return r.json()

    tree_sha = get("/git/commits/" + head)["tree"]["sha"]
    tree = get("/git/trees/" + tree_sha, params={"recursive": 1})
    eligible = [f for f in tree["tree"] if f["type"] == "blob" and
                f["mode"] in {"100644", "100755"} and editable(f["path"])]
    pieces, files, chars = [], {}, 0
    for entry in sorted(eligible, key=lambda x: x["path"]):
        if len(files) >= 50 or entry.get("size", 0) > 50_000 - chars:
            continue
        blob = get("/git/blobs/" + entry["sha"])
        try:
            text = base64.b64decode(blob["content"]).decode()
        except UnicodeDecodeError:
            continue
        if not text.strip() or "\0" in text:
            continue
        diff = snippet_diff(text if text.endswith("\n") else text + "\n", entry["path"])
        if chars + len(diff) > 50_000:
            continue
        files[entry["path"]] = text
        pieces.append(diff)
        chars += len(diff)
    note = f"Baseline reviewed {len(files)} of {len(eligible)} eligible source files in the returned tree."
    if tree.get("truncated"):
        note += " GitHub truncated the tree listing."
    return InMemoryRepo("".join(pieces), files), note
