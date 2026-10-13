"""Mutation test of the semantic judge: large-n, cleanly labelled bad diffs from known-good ones.

  python3 mutate.py gen [--per-diff 3]     mutants of every correct, distinct diff in results/runs.jsonl;
                                           each mutant is kept only if the hidden oracle FAILS on it (a real bug,
                                           not an equivalent mutant); records Ariadne's real verifier on it too
  python3 mutate.py judge --judge MODEL    judge every kept mutant (same prompt/parser/temperature as cmd_judge)
  python3 mutate.py report

Mutations touch only lines the diff adds to non-test .py files, one site per mutant, and keep the line
count, so the hunk headers stay valid. Good-diff verdicts are reused from results/judge_<model>.jsonl.
"""
import argparse, hashlib, json, math, random, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp  # noqa: E402
from tasks import TASKS  # noqa: E402

OUT = exp.RESULTS / "mutants.jsonl"

# (name, pattern, replacement). Applied at one match site.
OPERATORS = [
    ("lt_to_le", r"(?<![<>=!])<(?![<=])", "<="), ("le_to_lt", r"<=", "<"),
    ("gt_to_ge", r"(?<![<>=!-])>(?![>=])", ">="), ("ge_to_gt", r">=", ">"),
    ("eq_to_ne", r"==", "!="), ("ne_to_eq", r"!=", "=="),
    ("and_to_or", r"\band\b", "or"), ("or_to_and", r"\bor\b", "and"),
    ("drop_not", r"\bnot\s+", ""),
    ("plus_to_minus", r"(?<=[\w\)\]]) \+ (?=[\w\(\[])", " - "), ("minus_to_plus", r"(?<=[\w\)\]]) - (?=[\w\(\[])", " + "),
    ("int_plus_one", r"(?<![\w.])(\d+)(?![\w.])", None),  # n -> n+1
    ("raise_to_pass", r"^(\s*)raise\b.*$", None),
    ("return_none", r"^(\s*)return\s+\S.*$", None),
]


def sites(diff_text):
    """(line_index, op_name, match) for every mutable site on added lines of non-test .py files."""
    out, path = [], None
    lines = diff_text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            continue
        if not line.startswith("+") or line.startswith("+++") or not path or not path.endswith(".py"):
            continue
        if "test" in Path(path).name or path.startswith("tests/"):
            continue
        body = line[1:]
        s = body.strip()
        if not s or s.startswith(("#", '"""', "'''", "import ", "from ")) or s.startswith(("def ", "class ")):
            continue
        for name, pat, _ in OPERATORS:
            for m in re.finditer(pat, body, flags=re.M):
                if body[:m.start()].count('"') % 2 or body[:m.start()].count("'") % 2:
                    continue  # inside a string literal
                out.append((i, name, m.start(), m.end()))
    return out


def apply_site(diff_text, site):
    i, name, a, b = site
    lines = diff_text.split("\n")
    body = lines[i][1:]
    pat, rep = next((p, r) for n, p, r in OPERATORS if n == name)
    m = re.compile(pat, flags=re.M).match(body, a) if name not in ("raise_to_pass", "return_none") else re.match(pat, body)
    if name == "int_plus_one":
        new = body[:a] + str(int(body[a:b]) + 1) + body[b:]
    elif name == "raise_to_pass":
        new = re.match(r"^(\s*)", body).group(1) + "pass"
    elif name == "return_none":
        new = re.match(r"^(\s*)", body).group(1) + "return None"
    else:
        new = body[:a] + rep + body[b:]
    if new == body:
        return None, None, None
    lines[i] = "+" + new
    return "\n".join(lines), body, new


def worker_repo_with(task, diff_text):
    """The fixture with the diff applied, standing in for the worker's tree (for causal-chain test lookup)."""
    repo = exp.make_repo(task["files"])
    p = repo.parent / "m.diff"
    p.write_text(diff_text)
    ok = exp.git(repo, "apply", str(p), check=False).returncode == 0
    return repo, ok


def cmd_gen(per_diff, seed=13):
    rng = random.Random(seed)
    done = {r["source_run_id"] for r in exp.load(OUT)}
    seen = set()
    for rec in exp.load(exp.RESULTS / "runs.jsonl"):
        if rec["empty"] or not rec["oracle_pass"]:
            continue
        key = hashlib.sha256(rec["diff"].encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        if rec["run_id"] in done:
            continue
        task = TASKS[rec["task"]]
        cands = sites(rec["diff"])
        rng.shuffle(cands)
        kept, tried = 0, 0
        for site in cands:
            if kept >= per_diff:
                break
            mutated, before, after = apply_site(rec["diff"], site)
            if mutated is None:
                continue
            tried += 1
            o = exp.oracle(task, mutated)
            if o["oracle_pass"] or o["oracle_out"].startswith("diff did not apply"):
                continue  # equivalent mutant, or broke the patch
            repo, ok = worker_repo_with(task, mutated)
            if not ok:
                shutil.rmtree(repo.parent, ignore_errors=True)
                continue
            mid = f"{rec['run_id']}-m{kept}"
            v = exp.verify(task, repo, mutated, mid)
            shutil.rmtree(repo.parent, ignore_errors=True)
            exp.append(OUT, dict(mutant_id=mid, source_run_id=rec["run_id"], source_model=rec["model"], task=rec["task"],
                                 category=rec["category"], operator=site[1], before=before, after=after, diff=mutated,
                                 oracle_out=o["oracle_out"], **v))
            kept += 1
        if kept == 0:
            exp.append(OUT, dict(mutant_id=None, source_run_id=rec["run_id"], task=rec["task"], note=f"no killable mutant ({tried} tried, {len(cands)} sites)"))
        print(f"{rec['task']:12} {rec['model']:24} sites={len(cands):3} tried={tried:3} kept={kept}", flush=True)


def cmd_judge(judge_model):
    out = exp.RESULTS / f"mutant_judge_{judge_model.replace(':', '_').replace('/', '_')}.jsonl"
    done = {r["mutant_id"] for r in exp.load(out)}
    for m in exp.load(OUT):
        if not m.get("mutant_id") or m["mutant_id"] in done:
            continue
        verdict, text = exp.judge_one(judge_model, TASKS[m["task"]]["prompt"], m["diff"], m.get("verification"))
        exp.append(out, dict(mutant_id=m["mutant_id"], judge=judge_model, verdict=verdict, reasoning=text[:1500]))
        print(f"{m['task']:12} {m['operator']:14} verifier={m['verifier_pass']!s:5} judge={verdict}", flush=True)
    subprocess.run(["ollama", "stop", judge_model], capture_output=True)


def wilson(k, n, z=1.96):
    if n == 0:
        return "-"
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{k}/{n} = {p:.0%} [{max(c - h, 0):.0%}, {min(c + h, 1):.0%}]"


def cmd_report():
    muts = [m for m in exp.load(OUT) if m.get("mutant_id")]
    runs = {r["run_id"]: r for r in exp.load(exp.RESULTS / "runs.jsonl")}
    goods, seen = [], set()
    for r in runs.values():
        if not r["empty"] and r["oracle_pass"]:
            k = hashlib.sha256(r["diff"].encode()).hexdigest()
            if k not in seen:
                seen.add(k); goods.append(r)
    print(f"{len(muts)} killable mutants from {len(goods)} distinct correct diffs; "
          f"{sum(bool(m['verifier_pass']) for m in muts)} of them pass Ariadne's verifier (the judge's real workload)")
    by_op = {}
    for m in muts:
        by_op.setdefault(m["operator"], [0, 0])[0] += 1
        by_op[m["operator"]][1] += bool(m["verifier_pass"])
    print("by operator (mutants, of which verifier-passing):", {k: tuple(v) for k, v in sorted(by_op.items())})
    for f in sorted(exp.RESULTS.glob("mutant_judge_*.jsonl")):
        js = {j["mutant_id"]: j["verdict"] for j in exp.load(f)}
        jm = exp.load(f)[0]["judge"] if js else f.stem
        good_js = {j["run_id"]: j["verdict"] for j in exp.load(exp.RESULTS / f"judge_{f.stem[len('mutant_judge_'):]}.jsonl")}
        caught_all = sum(js.get(m["mutant_id"]) != "approved" for m in muts if m["mutant_id"] in js)
        hard = [m for m in muts if m["verifier_pass"] and m["mutant_id"] in js]
        caught_hard = sum(js[m["mutant_id"]] != "approved" for m in hard)
        g = [r for r in goods if r["run_id"] in good_js]
        false_rej = sum(good_js[r["run_id"]] != "approved" for r in g)
        print(f"\nJudge {jm}:")
        print(f"  catches bad diffs (not approved), all mutants:       {wilson(caught_all, len([m for m in muts if m['mutant_id'] in js]))}")
        print(f"  catches bad diffs that passed the verifier:          {wilson(caught_hard, len(hard))}")
        print(f"  false-rejects correct diffs (not approved):          {wilson(false_rej, len(g))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gen", "judge", "report"])
    ap.add_argument("--per-diff", type=int, default=3)
    ap.add_argument("--judge")
    a = ap.parse_args()
    {"gen": lambda: cmd_gen(a.per_diff), "judge": lambda: cmd_judge(a.judge), "report": cmd_report}[a.cmd]()
