"""Gate experiment runner: one headless Claude Code session per (task, arm, rep).

    python bench/run.py --task C1 --arm a --rep 1
    python bench/run.py --plan phase1 --reps 3          # all tasks x arms a,c, interleaved, skips finished runs
    python bench/run.py --probe                         # step 0: does UserPromptSubmit additionalContext reach the model?

Each run: fresh copy of shopdemo (+ task setup) in bench/work/<id>, its own git repo and seeded DB,
project-only settings (the user's own hooks do not fire), then grading. Results go to bench/runs/<id>/.
"""
import argparse
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

BENCH = Path(__file__).resolve().parent
WORK, RUNS = BENCH / "work", BENCH / "runs"
TASKS = json.loads((BENCH / "tasks" / "tasks.json").read_text(encoding="utf-8"))
DEFAULT_MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 25 * 60
ALLOW = ["Read", "Edit", "Write", "Glob", "Grep", "Bash(python:*)", "Bash(python -m unittest:*)", "Bash(git status:*)",
         "Bash(git diff:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)", "mcp__playwright"]


def claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("claude CLI not found on PATH")
    return exe


def project_slug(path: Path) -> str:
    """Folder name Claude Code uses under ~/.claude/projects for a working directory."""
    return "".join(c if c.isalnum() else "-" for c in str(path))


def prepare(task: str, arm: str, run_id: str) -> Path:
    work = WORK / run_id
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(BENCH / "shopdemo", work, ignore=shutil.ignore_patterns("*.db", "__pycache__"))
    setup = TASKS[task]["setup"]
    if setup:
        subprocess.run([sys.executable, str(BENCH / "tasks" / setup)], cwd=work, check=True)
    shutil.copy(BENCH / "arms" / "CLAUDE.md", work / "CLAUDE.md")
    settings = {"permissions": {"allow": ALLOW}}
    if arm in ("b", "c"):
        pack = BENCH / "packs" / f"{task}.md" if arm == "c" else BENCH / "packs_auto" / f"{task}.md"
        cmd = f'"{Path(sys.executable).as_posix()}" "{(BENCH / "inject.py").as_posix()}" "{pack.as_posix()}" ' \
              f'"{(RUNS / run_id / "inject.log").as_posix()}"'
        settings["hooks"] = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]}
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "-c", "user.name=bench", "-c", "user.email=bench@example.test", "commit", "-qm", "base"],
                   cwd=work, check=True)
    subprocess.run([sys.executable, "seed.py"], cwd=work, check=True, capture_output=True)
    return work


def wait_port(port: int, seconds: float = 10) -> None:
    end = time.time() + seconds
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"app did not start on port {port}")


def mcp_config(out: Path) -> Path:
    cli = BENCH / "node_modules" / "@playwright" / "mcp" / "cli.js"
    cfg = {"mcpServers": {"playwright": {"command": "node", "args": [str(cli), "--headless", "--isolated"]}}}
    out.write_text(json.dumps(cfg), encoding="utf-8")
    return out


def run_claude(work: Path, prompt: str, model: str, run_dir: Path, browser: bool) -> dict:
    sid = str(uuid.uuid4())
    cmd = [claude_exe(), "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
           "--setting-sources", "project", "--permission-mode", "acceptEdits", "--session-id", sid]
    if browser:
        cmd += ["--mcp-config", str(mcp_config(run_dir / "mcp.json")), "--strict-mcp-config"]
    else:
        cmd += ["--strict-mcp-config"]
    t0 = time.time()
    with open(run_dir / "stream.jsonl", "w", encoding="utf-8") as out:
        try:
            proc = subprocess.run(cmd, cwd=work, stdout=out, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                  timeout=TIMEOUT_S)
            rc, err = proc.returncode, proc.stderr[-2000:]
        except subprocess.TimeoutExpired:
            rc, err = -1, "timeout"
    result = {}
    for line in (run_dir / "stream.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") == "result":
            result = row
    transcript = Path.home() / ".claude" / "projects" / project_slug(work) / f"{sid}.jsonl"
    if transcript.exists():
        shutil.copy(transcript, run_dir / "transcript.jsonl")
        sub = transcript.with_suffix("") / "subagents"
        if sub.is_dir():
            shutil.copytree(sub, run_dir / "subagents", dirs_exist_ok=True)
    return {"session_id": sid, "returncode": rc, "stderr": err, "seconds": round(time.time() - t0, 1),
            "num_turns": result.get("num_turns"), "cost_usd": result.get("total_cost_usd"),
            "is_error": result.get("is_error"), "final_text": result.get("result") or ""}


def grade(task: str, work: Path, final_text: str, run_dir: Path) -> dict:
    if TASKS[task]["type"] == "browser":
        (run_dir / "final.txt").write_text(final_text, encoding="utf-8")
        out = subprocess.run([sys.executable, str(BENCH / "hidden" / "grade_browser.py"), task, str(work / "shopdemo.db"),
                              str(run_dir / "final.txt")], capture_output=True, text=True, encoding="utf-8")
        return json.loads(out.stdout) if out.returncode == 0 else {"success": False, "detail": out.stderr[-500:]}
    hidden = work / "tests_hidden"
    shutil.copytree(BENCH / "hidden" / task, hidden, dirs_exist_ok=True)
    (hidden / "__init__.py").touch()
    h = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests_hidden", "-t", "."], cwd=work,
                       capture_output=True, text=True)
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=work,
                       capture_output=True, text=True)
    return {"success": h.returncode == 0 and p.returncode == 0, "hidden_ok": h.returncode == 0,
            "public_ok": p.returncode == 0, "detail": (h.stderr + p.stderr)[-1500:]}


def run_one(task: str, arm: str, rep: int, model: str) -> dict:
    run_id = f"{task}-{arm}-{rep}"
    run_dir = RUNS / run_id
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    work = prepare(task, arm, run_id)
    browser = TASKS[task]["type"] == "browser"
    server = None
    try:
        if browser:
            server = subprocess.Popen([sys.executable, "-m", "shopdemo.web.server", "--port", "8800"], cwd=work,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_port(8800)
        res = run_claude(work, TASKS[task]["prompt"], model, run_dir, browser)
    finally:
        if server:
            server.terminate()
            server.wait(10)
    res.update(task=task, arm=arm, rep=rep, model=model, grade=grade(task, work, res["final_text"], run_dir))
    (run_dir / "result.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def probe(model: str) -> None:
    """Step 0: a nonce added only by the hook must come back in the answer, 3 times out of 3."""
    ok = 0
    for i in range(3):
        nonce = uuid.uuid4().hex[:8]
        run_id = f"probe-{i}"
        run_dir = RUNS / run_id
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True)
        work = WORK / run_id
        shutil.rmtree(work, ignore_errors=True)
        (work / ".claude").mkdir(parents=True)
        pack = run_dir / "pack.md"
        pack.write_text(f"Ma kiem tra cua phien nay la {nonce}.", encoding="utf-8")
        cmd = f'"{Path(sys.executable).as_posix()}" "{(BENCH / "inject.py").as_posix()}" "{pack.as_posix()}" ' \
              f'"{(run_dir / "inject.log").as_posix()}"'
        (work / ".claude" / "settings.json").write_text(json.dumps(
            {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": cmd, "timeout": 10}]}]}}),
            encoding="utf-8")
        res = run_claude(work, "Trong ngữ cảnh của bạn có một mã kiểm tra 8 ký tự. Chỉ in đúng mã đó, không gì khác.",
                         model, run_dir, False)
        hit = nonce in res["final_text"]
        ok += hit
        print(f"probe {i}: nonce={nonce} answer={res['final_text'].strip()[:40]!r} -> {'OK' if hit else 'MISS'}")
    print(f"step 0: {ok}/3")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--arm", choices=["a", "b", "c"])
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--plan", choices=["phase1", "phase2"])
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    RUNS.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    if args.probe:
        return probe(args.model)
    if args.plan:
        arms = ["a", "c"] if args.plan == "phase1" else ["a", "b"]
        jobs = [(t, a, r) for r in range(1, args.reps + 1) for t in TASKS for a in arms]
        random.Random(args.seed).shuffle(jobs)
        for t, a, r in jobs:
            if (RUNS / f"{t}-{a}-{r}" / "result.json").exists():
                continue
            res = run_one(t, a, r, args.model)
            print(f"{t}-{a}-{r}: success={res['grade']['success']} turns={res['num_turns']} "
                  f"cost={res['cost_usd']} {res['seconds']}s", flush=True)
        return
    res = run_one(args.task, args.arm, args.rep, args.model)
    print(json.dumps({k: res[k] for k in ("task", "arm", "rep", "num_turns", "cost_usd", "seconds", "grade")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
