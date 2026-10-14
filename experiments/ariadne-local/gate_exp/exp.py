"""Does Ariadne's gate make what lands better? Paired experiment, local models only.

  python3 exp.py gen   --models M1,M2 --reps 3     worker runs; each diff is immediately put through
                                                    Ariadne's real CausalSliceVerifier and the hidden oracle
  python3 exp.py judge --judge MODEL                semantic review of every non-empty diff, using
                                                    semantic_review.py's real prompt and verdict parser
  python3 exp.py report [--judge MODEL]

Arms, computed from the same diff (paired):
  none      everything the worker produces lands
  verifier  lands iff CausalSliceVerifier passes (orchestrator phase 1)
  full      lands iff the verifier passes AND the judge says APPROVE (orchestrator's autonomous path;
            anything else goes to NEEDS_REVIEW, counted as human queue, not landed)
Ground truth: hidden oracle tests the worker and the gate never see.

Results append to results/*.jsonl, keyed by run_id; reruns skip finished runs.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time, uuid
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "ariadne_src"))  # pinned: snapshot ad1675c + PR #24 atomic-commit fix (see ariadne_src/BACKPORT)

from tasks import TASKS  # noqa: E402
from daedalus.ariadne.diff_bus import Diff  # noqa: E402
from daedalus.ariadne.verification import CausalSliceVerifier, extract_causal_chain  # noqa: E402
from daedalus.ariadne.semantic_review import (  # noqa: E402
    _REVIEW_PROMPT_TEMPLATE, _parse_verdict, _verification_summary, VerificationResult)

OLLAMA = "http://localhost:11434"
NUM_CTX = 16384
MAX_STEPS = 15
RESULTS = HERE / "results"
# EXP_RUNS selects the runs file (default "runs"), so other arms get their own runs and judge files
RUNS_NAME = os.environ.get("EXP_RUNS", "runs")
RUNS_FILE = RESULTS / f"{RUNS_NAME}.jsonl"
JUDGE_PREFIX = "judge_" if RUNS_NAME == "runs" else f"judge_{RUNS_NAME}_"
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]

TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List files in the project.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's full contents.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file",
     "description": "Overwrite a file with the complete new contents (whole file, not a patch).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_tests", "description": "Run the project's pytest suite.",
     "parameters": {"type": "object", "properties": {}}}},
]
SYSTEM = ("You are a coding worker. Use the tools to complete the task in the project. Read files before "
          "changing them. write_file replaces the whole file. Run the tests when done. When the task is "
          "complete, reply with a one-line summary and no tool call.")


# ---------- helpers ----------

def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def make_repo(files: dict) -> Path:
    repo = Path(tempfile.mkdtemp(prefix="gate-exp-")) / "project"
    for rel, content in {"conftest.py": "", **files, ".gitignore": "__pycache__/\n.pytest_cache/\n"}.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return repo


def load(path: Path) -> list:
    return [json.loads(line) for line in path.open()] if path.exists() else []


def append(path: Path, rec: dict):
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def chat(model, messages, tools=None, temperature=0.6):
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"num_ctx": NUM_CTX, "temperature": temperature}}
    if tools:
        body["tools"] = tools
    r = httpx.post(f"{OLLAMA}/api/chat", json=body, timeout=900)
    data = r.json()
    if "message" not in data:
        raise RuntimeError(data.get("error", data))
    record_usage(model, data, sum(len(json.dumps(m)) for m in messages) + (len(json.dumps(tools)) if tools else 0))
    return data["message"]


# Token accounting per model. Ollama's prompt_eval_count skips prefix tokens it reuses from its KV cache;
# a hosted API bills the full context every call (cache reads at a discount), so also keep the size of
# everything sent, in characters, for a full-context estimate (~4 chars/token).
USAGE: dict = {}


def record_usage(model, data, sent_chars):
    u = USAGE.setdefault(model, {"calls": 0, "prompt_eval": 0, "completion": 0, "sent_chars": 0, "recv_chars": 0})
    msg = data.get("message") or {}
    u["calls"] += 1
    u["prompt_eval"] += data.get("prompt_eval_count", 0) or 0
    u["completion"] += data.get("eval_count", 0) or 0
    u["sent_chars"] += sent_chars
    u["recv_chars"] += len(msg.get("content") or "") + len(msg.get("thinking") or "") + len(json.dumps(msg.get("tool_calls") or []))


def stored_verification(d: dict | None):
    """VerificationResult.to_dict() nests its fields; rebuild the dataclass from that shape."""
    if not d:
        return None
    return VerificationResult(
        diff_id=d["diff_id"], passed=d["passed"], duration_seconds=d["duration_seconds"],
        typecheck_passed=d["typecheck"]["passed"], typecheck_errors=d["typecheck"]["errors"],
        lint_passed=d["lint"]["passed"], lint_errors=d["lint"]["errors"],
        tests_passed=d["tests"]["passed"], tests_run=d["tests"]["run"], tests_failed=d["tests"]["failed"],
        test_errors=d["tests"]["errors"], modules_checked=d["scope"]["modules"], tests_executed=d["scope"]["tests"])


# ---------- worker ----------

def run_tool(repo: Path, name: str, args: dict) -> str:
    def safe(p):
        t = (repo / p).resolve()
        if not str(t).startswith(str(repo.resolve())):
            raise ValueError("path outside project")
        return t
    if name == "list_files":
        return "\n".join(str(p.relative_to(repo)) for p in sorted(repo.rglob("*"))
                         if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts)
    if name == "read_file":
        return safe(args["path"]).read_text()
    if name == "write_file":
        t = safe(args["path"])
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(args["content"])
        return f"wrote {args['path']} ({len(args['content'])} chars)"
    if name == "run_tests":
        r = subprocess.run(PYTEST, cwd=repo, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr)[-3000:]
    return f"unknown tool {name}"


def icarus_identity() -> str:
    """The identity load_icarus_identity() is meant to load (it falls back to a stub; gameplan T-e13), frontmatter stripped."""
    text = (HERE.parent / "mature" / "base" / ".claude-plugin" / "agents" / "icarus.md").read_text()
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def system_prompt(arm: str) -> str:
    return SYSTEM if arm == "D" else icarus_identity() + "\n\n## In this environment\n" + SYSTEM


def work(model: str, repo: Path, prompt: str, max_steps: int = MAX_STEPS, system: str = None) -> dict:
    msgs = [{"role": "system", "content": system or SYSTEM}, {"role": "user", "content": prompt}]
    t0, calls, bad, steps, final, err = time.time(), 0, 0, 0, "", None
    try:
        for steps in range(1, max_steps + 1):
            msg = chat(model, msgs, TOOLS)
            msgs.append({k: msg[k] for k in ("role", "content", "tool_calls") if k in msg})
            tcs = msg.get("tool_calls") or []
            if not tcs:
                final = msg.get("content") or ""
                break
            for tc in tcs:
                calls += 1
                name = tc["function"]["name"]
                args = tc["function"].get("arguments") or {}
                try:
                    if isinstance(args, str):
                        args = json.loads(args)
                    out = run_tool(repo, name, args)
                except Exception as e:
                    bad += 1
                    out = f"error: {e}"
                msgs.append({"role": "tool", "content": out, "tool_name": name})
        else:
            err = "max_steps"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    return dict(steps=steps, tool_calls=calls, bad_calls=bad, final=final[:500], worker_error=err,
                worker_secs=round(time.time() - t0, 1))


# ---------- gate + oracle (no model) ----------

def harness_diff(repo: Path) -> str:
    """Exactly what IcarusWorker.submit_diff_to_ariadne does."""
    git(repo, "add", "-A")
    return git(repo, "diff", "--cached", "HEAD").stdout


def verify(task: dict, worker_repo: Path, diff_text: str, run_id: str) -> dict:
    base = make_repo(task["files"])
    diff = Diff.from_git_diff(work_id=run_id, instance_id="exp", diff_content=diff_text,
                              description=task["prompt"])
    chain = extract_causal_chain(diff, worker_repo)  # the harness computes it in the worker's tree
    noop = [sys.executable, "-c", "pass"]  # typecheck/lint off, as in the hermetic tier
    v = CausalSliceVerifier(base, typecheck_cmd=noop, lint_cmd=noop, test_cmd=PYTEST).verify(diff, chain)
    shutil.rmtree(base.parent, ignore_errors=True)
    return dict(verifier_pass=v.passed, verifier_tests_run=v.tests_run, verifier_tests_failed=v.tests_failed,
                verifier_test_files=chain.test_files, verification=v.to_dict())


def oracle(task: dict, diff_text: str) -> dict:
    repo = make_repo(task["files"])
    try:
        if diff_text.strip():
            p = repo.parent / "change.diff"
            p.write_text(diff_text)
            applied = git(repo, "apply", str(p), check=False)
            if applied.returncode != 0:
                return dict(oracle_pass=False, oracle_out="diff did not apply: " + applied.stderr[-300:])
        shutil.rmtree(repo / "tests", ignore_errors=True)
        (repo / "tests").mkdir()
        (repo / "tests" / "test_oracle.py").write_text(task["oracle"])
        try:
            r = subprocess.run(PYTEST, cwd=repo, capture_output=True, text=True, timeout=60)
            return dict(oracle_pass=r.returncode == 0, oracle_out=r.stdout.strip().splitlines()[-1][:200])
        except subprocess.TimeoutExpired:
            return dict(oracle_pass=False, oracle_out="timeout")
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)


def touched_existing_tests(task: dict, diff_text: str) -> bool:
    existing = [f for f in task["files"] if f.startswith("tests/")]
    return any(f"a/{f} " in line for line in diff_text.splitlines() if line.startswith("diff --git") for f in existing)


def cmd_gen(models, reps, tasks, arm="D"):
    out = RUNS_FILE
    done = {(r["model"], r["task"], r["rep"]) for r in load(out)}
    for model in models:
        for name in tasks:
            task = TASKS[name]
            for rep in range(1, reps + 1):
                if (model, name, rep) in done:
                    continue
                run_id = uuid.uuid4().hex[:12]
                repo = make_repo(task["files"])
                w = work(model, repo, task["prompt"], system=system_prompt(arm))
                diff_text = harness_diff(repo)
                rec = dict(run_id=run_id, arm=arm, model=model, task=name, category=task["category"], rep=rep, **w,
                           diff=diff_text, empty=not diff_text.strip(),
                           touched_existing_tests=touched_existing_tests(task, diff_text))
                if diff_text.strip():
                    rec.update(verify(task, repo, diff_text, run_id))
                else:
                    rec.update(verifier_pass=None)
                rec.update(oracle(task, diff_text) if diff_text.strip() else dict(oracle_pass=None, oracle_out="no diff"))
                append(out, rec)
                shutil.rmtree(repo.parent, ignore_errors=True)
                print(f"{model:24} {name:12} rep{rep} empty={rec['empty']!s:5} verifier={rec['verifier_pass']!s:5} "
                      f"oracle={rec['oracle_pass']!s:5} err={w['worker_error']} {w['worker_secs']}s", flush=True)
        subprocess.run(["ollama", "stop", model], capture_output=True)


# ---------- judge ----------

def cmd_judge(judge_model):
    out = RESULTS / f"{JUDGE_PREFIX}{judge_model.replace(':', '_').replace('/', '_')}.jsonl"
    done = {r["run_id"] for r in load(out)}
    for rec in load(RUNS_FILE):
        if rec["empty"] or rec["run_id"] in done:
            continue
        task = TASKS[rec["task"]]
        v = rec.get("verification")
        vr = stored_verification(v)
        prompt = _REVIEW_PROMPT_TEMPLATE.format(intent=task["prompt"], diff_content=rec["diff"],
                                                verification_summary=_verification_summary(vr))
        t0 = time.time()
        try:
            text = chat(judge_model, [{"role": "user", "content": prompt}], temperature=0).get("content") or ""
            verdict = _parse_verdict(text).value
        except Exception as e:
            text, verdict = f"judge error: {e}", "needs_human"
        append(out, dict(run_id=rec["run_id"], judge=judge_model, verdict=verdict, reasoning=text[:1500],
                         judge_secs=round(time.time() - t0, 1)))
        print(f"{rec['model']:24} {rec['task']:12} rep{rec['rep']} oracle={rec['oracle_pass']!s:5} judge={verdict}", flush=True)
    subprocess.run(["ollama", "stop", judge_model], capture_output=True)


# ---------- retry arm ----------

def judge_file(judge_model):
    return RESULTS / f"{JUDGE_PREFIX}{judge_model.replace(':', '_').replace('/', '_')}.jsonl"


def judge_one(judge_model, intent, diff_text, verification: dict | None):
    vr = stored_verification(verification)
    prompt = _REVIEW_PROMPT_TEMPLATE.format(intent=intent, diff_content=diff_text,
                                            verification_summary=_verification_summary(vr))
    try:
        text = chat(judge_model, [{"role": "user", "content": prompt}], temperature=0).get("content") or ""
        return _parse_verdict(text).value, text
    except Exception as e:
        return "needs_human", f"judge error: {e}"


def cmd_retry(judge_model):
    """One retry, same model, fresh start, for every non-empty diff the full arm didn't land.

    Feedback follows the real orchestrator's order: a verifier failure means the judge never ran, so
    the worker gets the verifier's errors; a verified diff the judge didn't approve gets the judge's
    reasoning.
    """
    out = RESULTS / f"retry_{judge_model.replace(':', '_').replace('/', '_')}.jsonl"
    done = {r["run_id"] for r in load(out)}
    judged = {j["run_id"]: j for j in load(judge_file(judge_model))}
    runs = sorted(load(RUNS_FILE), key=lambda r: r["model"])
    for rec in runs:
        if rec["empty"] or rec["run_id"] in done or rec["run_id"] not in judged:
            continue
        j = judged[rec["run_id"]]
        if rec["verifier_pass"] and j["verdict"] == "approved":
            continue  # landed first time
        task = TASKS[rec["task"]]
        if not rec["verifier_pass"]:
            v = rec.get("verification") or {}
            trigger = "verifier"
            errs = (v.get("tests") or {}).get("errors") or []
            feedback = ("Automated verification rejected it: " + _verification_summary(stored_verification(v))
                        + ("\n" + "\n".join(errs) if errs else ""))
        else:
            trigger = "judge"
            feedback = "A code reviewer did not approve it:\n" + j["reasoning"]
        prompt = (f"{task['prompt']}\n\nA previous attempt at this task was not accepted.\n\n"
                  f"Previous attempt's diff:\n```diff\n{rec['diff']}\n```\n\n{feedback}\n\n"
                  "The project is back at the original code. Complete the task, taking the feedback into account.")
        repo = make_repo(task["files"])
        w = work(rec["model"], repo, prompt)
        diff_text = harness_diff(repo)
        r2 = dict(run_id=rec["run_id"], model=rec["model"], task=rec["task"], category=rec["category"],
                  trigger=trigger, **w, diff=diff_text, empty=not diff_text.strip())
        if diff_text.strip():
            r2.update(verify(task, repo, diff_text, rec["run_id"] + "-r"))
            r2.update(oracle(task, diff_text))
            if r2["verifier_pass"]:
                r2["verdict"], r2["reasoning"] = judge_one(judge_model, task["prompt"], diff_text, r2["verification"])
            else:
                r2["verdict"], r2["reasoning"] = None, None
        else:
            r2.update(verifier_pass=None, oracle_pass=None, verdict=None)
        r2["landed"] = bool(r2.get("verifier_pass")) and r2.get("verdict") == "approved"
        append(out, r2)
        shutil.rmtree(repo.parent, ignore_errors=True)
        print(f"{rec['model']:24} {rec['task']:12} trigger={trigger:8} first_oracle={rec['oracle_pass']!s:5} "
              f"retry: verifier={r2.get('verifier_pass')!s:5} judge={r2.get('verdict')} oracle={r2.get('oracle_pass')}",
              flush=True)


# ---------- report ----------

def cmd_report(judge_model=None):
    runs = load(RUNS_FILE)
    judges = {}
    for f in sorted(RESULTS.glob(f"{JUDGE_PREFIX}*.jsonl")):
        if JUDGE_PREFIX == "judge_" and f.name.startswith("judge_runs_"):
            continue  # another arm's judge file
        for j in load(f):
            judges.setdefault(j["judge"], {})[j["run_id"]] = j["verdict"]
    judge_names = [judge_model] if judge_model else list(judges)

    def arms(r):
        good = bool(r["oracle_pass"])
        a = {"none": not r["empty"], "verifier": bool(r["verifier_pass"])}
        for jn in judge_names:
            a[f"full[{jn}]"] = bool(r["verifier_pass"]) and judges.get(jn, {}).get(r["run_id"]) == "approved"
        return good, a

    def table(rows, label):
        arm_names = ["none", "verifier"] + [f"full[{jn}]" for jn in judge_names]
        print(f"\n{label}: {len(rows)} runs, {sum(bool(r['oracle_pass']) for r in rows)} correct diffs produced")
        print(f"  {'arm':28} {'landed':>6} {'bad landed':>10} {'precision':>9} {'yield':>7} {'false rej':>9}")
        for arm in arm_names:
            landed = bad = good_landed = false_rej = 0
            for r in rows:
                good, a = arms(r)
                if a[arm]:
                    landed += 1; bad += not good; good_landed += good
                elif good:
                    false_rej += 1
            prec = f"{good_landed / landed:.0%}" if landed else "-"
            print(f"  {arm:28} {landed:6} {bad:10} {prec:>9} {good_landed:3}/{len(rows):<3} {false_rej:9}")

    table(runs, "ALL WORKERS")
    for m in dict.fromkeys(r["model"] for r in runs):
        table([r for r in runs if r["model"] == m], m)
    print("\nBy category (all workers): bad landed per arm")
    for c in dict.fromkeys(r["category"] for r in runs):
        rows = [r for r in runs if r["category"] == c]
        cells = []
        for arm in ["none", "verifier"] + [f"full[{jn}]" for jn in judge_names]:
            bad = sum(1 for r in rows if arms(r)[1][arm] and not r["oracle_pass"])
            landed = sum(1 for r in rows if arms(r)[1][arm])
            cells.append(f"{arm}={bad}/{landed}")
        print(f"  {c:12} n={len(rows):3}  " + "  ".join(cells))
    for jn in judge_names:
        js = judges.get(jn, {})
        conf = {}
        for r in runs:
            if r["run_id"] in js:
                k = ("good" if r["oracle_pass"] else "bad", js[r["run_id"]])
                conf[k] = conf.get(k, 0) + 1
        print(f"\nJudge {jn} on all non-empty diffs (oracle x verdict): " +
              ", ".join(f"{g}/{v}={n}" for (g, v), n in sorted(conf.items())))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "judge", "retry", "report"])
    ap.add_argument("--models", default="")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--judge")
    ap.add_argument("--arm", default="D", choices=["A", "D"])
    a = ap.parse_args()
    if a.cmd == "gen":
        cmd_gen([m for m in a.models.split(",") if m], a.reps, a.tasks.split(","), a.arm)
    elif a.cmd == "judge":
        cmd_judge(a.judge)
    elif a.cmd == "retry":
        cmd_retry(a.judge)
    else:
        cmd_report(a.judge)
