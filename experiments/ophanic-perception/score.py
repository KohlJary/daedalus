#!/usr/bin/env python3
"""
score.py: score a run's calls and write its report (see DESIGN.md).

    python score.py results/<run> [--report REPORT-pilot.md] [--label PILOT] [--notes results/<run>/notes.md]

Normalises answers (case, whitespace, markdown, trailing punctuation, list order for set answers),
applies the ±5-point tolerance to proportions, and reports accuracy per cell with a Wilson 95% interval.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOLERANCE = 5
ENC_ORDER = ["ophanic@100", "ophanic@60", "ophanic-noise@100", "ophanic-noise@60", "prose", "json", "list"]
TYPE_ORDER = ["layout", "graph", "containment"]
SIZE_ORDER = ["small", "medium", "large"]


def clean(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"[*_`\"']", "", text)
    return text.strip()


def norm_name(s: str) -> str:
    s = re.sub(r"^\s*(answer|final answer)\s*:\s*", "", s.strip(), flags=re.I)
    s = re.sub(r"^\s*[-•]\s*", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .!,;:").lower()
    # "Archive panel" names the panel Archive: drop a trailing generic noun the questions themselves use
    return re.sub(r"^(?:the )?(.+?) (?:panel|node|group)$", r"\1", s)


def correct(question: dict, answer: str) -> bool:
    a = clean(answer)
    gold, atype = question["gold"], question["answer_type"]
    if atype == "name":
        first = next((line for line in a.splitlines() if line.strip()), "")
        return norm_name(first) == str(gold).lower()
    if atype == "yesno":
        m = re.search(r"[a-z]+", a.lower())
        return bool(m) and m.group(0) == gold
    if atype == "int":
        m = re.search(r"-?\d+", a)
        return bool(m) and int(m.group(0)) == int(gold)
    if atype == "percent":
        m = re.search(r"-?\d+(?:\.\d+)?", a)
        return bool(m) and abs(float(m.group(0)) - float(gold)) <= TOLERANCE
    if atype == "set":
        parts = re.split(r",|;|\n|\band\b", a)
        got = {norm_name(p) for p in parts if norm_name(p)}
        return got == {g.lower() for g in gold}
    raise ValueError(f"unknown answer type {atype}")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def cell(rows) -> str:
    n = len(rows)
    if not n:
        return "—"
    k = sum(r["correct"] for r in rows)
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% ({100 * lo:.0f}–{100 * hi:.0f}) n={n}"


def load(run_dir: Path) -> list[dict]:
    rows = []
    with (run_dir / "calls.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("error"):
                continue
            r["correct"] = correct(r, r["answer"])
            rows.append(r)
    return rows


def table(header: list[str], body: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return out + [""]


def report(run_dir: Path, rows: list[dict], label: str) -> str:
    encs = [e for e in ENC_ORDER if any(r["encoding"] == e for r in rows)]
    group = defaultdict(list)
    for r in rows:
        group[(r["encoding"],)].append(r)
        group[(r["encoding"], r["type"])].append(r)
        group[(r["encoding"], r["type"], r["size"])].append(r)
        group[(r["encoding"], r["type"], r["sub"])].append(r)
        group[(r["encoding"], r["type"], r["size"], r["sub"])].append(r)
    models = sorted({r["model"] for r in rows})
    tasks_files = sorted({r["tasks_file"] for r in rows})
    num_ctx = sorted({r.get("num_ctx") for r in rows})
    out = [f"# {label}: no hypothesis tested", "",
           f"**{label}.** This run exists to find harness bugs. Its numbers are descriptive only and test none of "
           "DESIGN.md's hypotheses; the confirmatory run uses fresh seeds and 40 structures per cell.", "",
           f"- Run: `{run_dir.name}`; model(s): {', '.join(models)}; tasks: {', '.join(tasks_files)}",
           f"- Calls scored: {len(rows)}; num_ctx: {num_ctx}",
           f"- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±{TOLERANCE} points.",
           ""]

    out += ["## Accuracy by encoding", ""]
    out += table(["encoding", "accuracy"], [[e, cell(group[(e,)])] for e in encs])

    out += ["## Encoding × structure", ""]
    out += table(["structure"] + encs, [[t] + [cell(group[(e, t)]) for e in encs] for t in TYPE_ORDER])

    out += ["## Encoding × structure × size", ""]
    out += table(["structure", "size"] + encs,
                 [[t, s] + [cell(group[(e, t, s)]) for e in encs] for t in TYPE_ORDER for s in SIZE_ORDER])

    subs = {t: sorted({r["sub"] for r in rows if r["type"] == t}) for t in TYPE_ORDER}
    kind_of = {r["sub"]: r["kind"] for r in rows}
    out += ["## Encoding × structure × question kind", ""]
    out += table(["structure", "question (kind)"] + encs,
                 [[t, f"{q} ({kind_of[q]})"] + [cell(group[(e, t, q)]) for e in encs]
                  for t in TYPE_ORDER for q in subs[t]])

    # Noise, on the structures that have a noise call, paired
    noisy = {(r["task"], r["question_id"]) for r in rows if r["encoding"] == "ophanic-noise@100"}
    if noisy:
        clean_rows = [r for r in rows if r["encoding"] == "ophanic@100" and (r["task"], r["question_id"]) in noisy]
        noise_rows = [r for r in rows if r["encoding"] == "ophanic-noise@100"]
        out += ["## Noise (paired: the same structures and questions)", ""]
        out += table(["structure", "ophanic@100", "ophanic-noise@100"],
                     [[t, cell([r for r in clean_rows if r["type"] == t]), cell([r for r in noise_rows if r["type"] == t])]
                      for t in TYPE_ORDER] + [["all", cell(clean_rows), cell(noise_rows)]])

    out += ["## Input tokens per encoding", "",
            "Mean `prompt_eval_count` reported by the model API per call (the encoding plus the question and "
            "instruction, under the model's chat template). The ratio is the mean of each call's count over the json call for the same structure and question.", ""]
    # Ratios are paired: each call against the json call for the same structure and question, since some
    # encodings (the noise variant) run on a subset of structures
    by_key = {(r["task"], r["question_id"], r["encoding"]): r.get("prompt_eval_count") for r in rows}
    tok, ratio = defaultdict(list), defaultdict(list)
    for r in rows:
        n = r.get("prompt_eval_count")
        if not n:
            continue
        tok[(r["encoding"], r["type"], r["size"])].append(n)
        js = by_key.get((r["task"], r["question_id"], "json"))
        if js:
            ratio[(r["encoding"], r["type"], r["size"])].append(n / js)
            ratio[(r["encoding"],)].append(n / js)
    body = []
    for t in TYPE_ORDER:
        for s in SIZE_ORDER:
            line = [t, s]
            for e in encs:
                v, rv = tok.get((e, t, s)), ratio.get((e, t, s))
                line.append(f"{statistics.mean(v):.0f}" + (f" ({statistics.mean(rv):.2f}×)" if rv else "") if v else "—")
            body.append(line)
    body.append(["all", ""] + [f"({statistics.mean(ratio[(e,)]):.2f}×)" if ratio.get((e,)) else "—" for e in encs])
    out += table(["structure", "size"] + encs, body)

    out += ["## Harness checks", ""]
    errs = run_dir / "calls.jsonl"
    all_lines = [json.loads(x) for x in errs.read_text(encoding="utf-8").splitlines() if x.strip()]
    n_err = sum(1 for r in all_lines if r.get("error"))
    empty = sum(1 for r in rows if not clean(r["answer"]))
    trunc = sum(1 for r in rows if r.get("prompt_eval_count") and r.get("num_ctx")
                and r["prompt_eval_count"] >= r["num_ctx"] - 8)
    long_answers = sum(1 for r in rows if len(clean(r["answer"])) > 200)
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    out += [f"- Calls with an error: {n_err}",
            f"- Empty answers: {empty}",
            f"- Prompts at or over num_ctx (would be truncated): {trunc}",
            f"- Answers over 200 characters: {long_answers}",
            f"- Latency: total {sum(lat) / 60:.1f} min, median {statistics.median(lat):.2f} s, "
            f"max {max(lat):.1f} s" if lat else "- Latency: —", ""]
    out += ["## All cells", ""]
    out += table(["structure", "size", "question"] + encs,
                 [[t, s, q] + [cell(group[(e, t, s, q)]) for e in encs]
                  for t in TYPE_ORDER for s in SIZE_ORDER for q in subs[t]])
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--report", default=None, help="output path (default: <run_dir>/REPORT.md)")
    ap.add_argument("--label", default="PILOT")
    ap.add_argument("--notes", default=None, help="a Markdown file of hand-written findings, inserted after the header")
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir)
    rows = load(run_dir)
    text = report(run_dir, rows, a.label)
    if a.notes:
        head, rest = text.split("## Accuracy by encoding", 1)
        text = head + Path(a.notes).read_text(encoding="utf-8").rstrip() + "\n\n## Accuracy by encoding" + rest
    path = Path(a.report) if a.report else run_dir / "REPORT.md"
    path.write_text(text + "\n", encoding="utf-8")
    k = sum(r["correct"] for r in rows)
    print(f"{len(rows)} calls, {k} correct; wrote {path}")


if __name__ == "__main__":
    main()
