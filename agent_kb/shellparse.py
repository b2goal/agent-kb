"""Shell command helpers: split compound commands, extract prefixes, rate risk, sign errors."""
from __future__ import annotations

import re
import shlex
from typing import List, Optional

HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2[ \t]*(?=\n|$)", re.S)
COMPOUND = re.compile(r"(^|[;&|]\s*)cd\s|&&|\|\||;|\$\(|`|\n")
TWO_WORD = {"git", "npm", "yarn", "pnpm", "pip", "python", "python3", "py", "uv", "poetry", "cargo", "go",
            "dotnet", "mvn", "gradle", "./gradlew", "docker", "kubectl", "sed", "npx", "bun"}
NEVER = ["rm", "sudo", "su", "dd", "mkfs", "chmod", "chown", "kill", "pkill", "killall", "shutdown", "reboot",
         "curl", "wget", "ssh", "scp", "rsync", "nc", "eval", "exec", "sh", "bash", "zsh", "powershell", "pwsh",
         "git push", "git reset", "git clean", "git checkout", "git rebase", "git filter-branch",
         "npm publish", "docker", "kubectl", "terraform", "aws", "gcloud", "az"]
REVIEW = ["python", "python3", "py", "node", "npx", "ruby", "perl", "php", "git commit", "git add", "git stash",
          "pip install", "npm install", "yarn add", "pnpm add", "mv", "cp", "mkdir", "touch", "sed -i", "make",
          "mvn", "gradle", "./gradlew"]
SAFE_EXACT = {"python -m pytest", "python -m unittest", "python3 -m pytest", "python3 -m unittest",
              "py -m pytest", "py -m unittest"}
TEST_HINT = re.compile(r"(pytest|unittest|jest|vitest|mocha|go test|cargo test|mvn .*test|gradle.*test|"
                       r"npm (run )?test|yarn test|pnpm test|dotnet test|rspec|phpunit|ctest)", re.I)
ERROR_LINE = re.compile(r"^\s*(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception|Failure))\b[:\s](.*)$", re.M)


def is_compound(cmd: str) -> bool:
    return bool(COMPOUND.search(HEREDOC.sub(" ", cmd or "").strip()))


def split_segments(cmd: str) -> List[str]:
    """Split on ; && || | newlines and $( ) / backticks, but not inside quotes."""
    segs, cur, quote, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(cmd):
                cur.append(cmd[i + 1])
                i += 1
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif cmd.startswith("$(", i) or ch in ";|&\n`()":
            segs.append("".join(cur))
            cur = []
            if cmd.startswith("$(", i):
                i += 1
        else:
            cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def prefixes(cmd: str) -> List[str]:
    """`cd x && npm test -- -u 2>&1 | tail` -> ['npm test', 'tail'] (cd ignored, heredoc bodies skipped)."""
    out = []
    cmd = re.sub(r"\d*>&\d+|&>", " ", HEREDOC.sub(" ", cmd or ""))
    for seg in split_segments(cmd):
        seg = re.sub(r"^(\w+=\S+\s+)+", "", seg)
        if not seg or seg.startswith(("#", "{", "}")):
            continue
        try:
            words = shlex.split(seg, posix=True)
        except ValueError:
            words = seg.split()
        if not words or words[0] in ("cd", "pushd", "popd", "true", "false", "then", "do", "done", "fi", "else"):
            continue
        first = words[0]
        if len(first) < 2 or not re.match(r"^[\w./-]+$", first):
            continue
        if first in ("python", "python3", "py") and len(words) > 2 and words[1] == "-m":
            out.append(f"{first} -m {words[2]}")
        elif first == "sed" and len(words) > 1 and words[1].startswith("-i"):
            out.append("sed -i")
        elif first in TWO_WORD and len(words) > 1 and not words[1].startswith("-"):
            out.append(f"{first} {words[1]}")
        else:
            out.append(first)
    return out


def risk(prefix: str) -> str:
    if prefix in SAFE_EXACT:
        return "safe"
    for p in NEVER:
        if prefix == p or prefix.startswith(p + " "):
            return "never"
    for p in REVIEW:
        if prefix == p or prefix.startswith(p + " "):
            return "review"
    return "safe"


def error_signature(text: str) -> Optional[str]:
    matches = ERROR_LINE.findall(text or "")
    if not matches:
        return None
    name, msg = matches[-1]
    msg = re.sub(r"(['\"]).*?\1", "'…'", msg.strip())
    msg = re.sub(r"[\w./\\-]*[/\\][\w./\\-]+", "<path>", msg)
    msg = re.sub(r"\b\d+(\.\d+)?\b", "N", msg)
    return f"{name.split('.')[-1]}: {msg[:100]}".strip()
