"""Project identity: the normalized git remote, so one project matches across machines."""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

GLOBAL = "global"


def normalize_remote(url: str) -> str:
    """git@github.com:Org/App.git, https://user@github.com/org/app -> github.com/org/app"""
    u = url.strip()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    u = re.sub(r"\.git/?$", "", u)
    if ":" in u.split("/")[0]:
        host, rest = u.split(":", 1)
        if not rest.isdigit():
            u = f"{host}/{rest}"
    return u.strip("/").lower()


@lru_cache(maxsize=256)
def project_id(cwd: str) -> str:
    path = Path(cwd or ".").resolve()
    try:
        top = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=3)
        root = top.stdout.strip() if top.returncode == 0 else ""
        if root:
            remote = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"],
                                    capture_output=True, text=True, timeout=3)
            if remote.returncode == 0 and remote.stdout.strip():
                return normalize_remote(remote.stdout)
            return "local:" + Path(root).as_posix()
    except (OSError, subprocess.SubprocessError):
        pass
    return "local:" + path.as_posix()


def slug(pid: str) -> str:
    """File-system friendly folder name for a project id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", pid).strip("_") or "project"
