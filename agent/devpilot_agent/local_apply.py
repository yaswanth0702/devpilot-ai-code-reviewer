"""Replace a local source file after the user approves the displayed patch."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile


def approve_replacement(path: Path, snapshot: bytes, fixed: str) -> int:
    try:
        answer = input(f"Apply these changes to {path}? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() not in {"y", "yes"}:
        print("Changes declined.")
        return 0

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as pending:
            temp_path = Path(pending.name)
            pending.write(fixed.encode("utf-8"))
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.read_bytes() != snapshot:
            print("The source changed during review. Review the current file again.", file=sys.stderr)
            return 2
        os.chmod(temp_path, stat.S_IMODE(info.st_mode))
        os.replace(temp_path, path)
    except OSError as exc:
        print(f"Could not apply the changes to {path}: {exc}", file=sys.stderr)
        return 2
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    print(f"Applied the reviewed changes to {path}.")
    return 0
