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


def per_cell(rows: list[dict]) -> str:
    counts = sorted({len({r["task"] for r in rows if (r["type"], r["size"]) == (t, s)})
                     for t in TYPE_ORDER for s in SIZE_ORDER} - {0})
    return "–".join(str(c) for c in counts) if counts else "0"


def table(header: list[str], body: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in body]
    return out + [""]


def kn(rows) -> str:
    """Like cell(), with the raw count first: '29/60 = 48% (36–61)'."""
    n = len(rows)
    if not n:
        return "—"
    k = sum(r["correct"] for r in rows)
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100 * k / n:.0f}% ({100 * lo:.0f}–{100 * hi:.0f})"


def number(answer: str):
    m = re.search(r"-?\d+(?:\.\d+)?", clean(answer))
    return float(m.group(0)) if m else None


def fmt(x: float) -> str:
    return f"{x:g}"


def review_checks(rows: list[dict], encs: list[str], tokens: list[dict]) -> list[str]:
    """The splits and baselines Momus asked for in the pilot review (trial 2026-10-15-ophanic-perception-pilot)."""
    main_arms = [e for e in encs if "noise" not in e]
    text_arms = [e for e in ("prose", "json", "list") if e in encs]
    by = defaultdict(list)
    for r in rows:
        by[(r["encoding"], r["type"], r["kind"])].append(r)
        by[(r["encoding"], r["type"], r["sub"])].append(r)
    out = ["## Checks from the pilot review", "",
           "Computed by score.py from calls.jsonl (and tokens.jsonl for the cost table), at Momus's request. "
           "Like everything else here, these are descriptive.", ""]

    # 1. Layout: spatial vs proportion
    out += ["### Layout: spatial questions versus the proportion question", "",
            "Spatial is `right_of` plus `below`; proportion is `share`. In the prose, json and list encodings the "
            "share is written down as a number, so for them the question is a lookup; in the ophanic encodings it "
            "has to be measured from character widths.", ""]
    out += table(["encoding", "layout spatial", "layout proportion"],
                 [[e, kn(by[(e, "layout", "spatial")]), kn(by[(e, "layout", "proportion")])] for e in encs])
    oph = by[("ophanic@100", "layout", "spatial")]
    txt = [sum(r["correct"] for r in by[(e, "layout", "spatial")]) for e in text_arms]
    if oph and txt:
        out += [f"On the spatial questions ophanic@100 got {sum(r['correct'] for r in oph)}/{len(oph)} and the "
                f"text arms {min(txt)}–{max(txt)}/{len(oph)}: no gap at this sample size. The layout deficit in the "
                "tables below comes from the proportion question.", ""]

    # 2. Proportion answers: the "25" default and a constant guess
    share = [r for r in rows if r["sub"] == "share"]
    if share:
        golds = {}
        for r in share:
            golds[(r["task"], r["question_id"])] = float(r["gold"])
        gl = list(golds.values())

        def hits(c):
            return sum(abs(c - g) <= TOLERANCE for g in gl)
        best = max(range(0, 101), key=lambda c: (hits(c), -abs(c - 25)))
        out += ["### Proportion answers: the \"25\" default and a constant-guess baseline", ""]
        body = []
        for e in encs:
            rs = [r for r in share if r["encoding"] == e]
            nums = [(number(r["answer"]), float(r["gold"])) for r in rs]
            errs = [abs(a - g) for a, g in nums if a is not None]
            body.append([e, str(len(rs)), str(sum(1 for a, _ in nums if a == 25)),
                         f"{statistics.mean(errs):.1f}" if errs else "—", kn(rs)])
        out += table(["encoding", "share calls", "answered exactly 25", "mean absolute error (points)", "accuracy"],
                     body)
        dist = sorted(defaultdict(int, {g: gl.count(g) for g in gl}).items())
        out += [f"Gold shares over the {len(gl)} share questions: "
                + ", ".join(f"{fmt(g)} ×{c}" for g, c in dist) + ".",
                f"Always answering 25 would score {hits(25)}/{len(gl)} = {100 * hits(25) / len(gl):.0f}% under the "
                f"±{TOLERANCE} rule" + ("; no other constant does better" if best == 25 else
                                     f"; the best constant ({best}) would score {hits(best)}/{len(gl)} = "
                                     f"{100 * hits(best) / len(gl):.0f}%") + ". An ophanic share accuracy at or below that is indistinguishable "
                "from a guess, and is no evidence that the model reads widths.", ""]

    # 3. Floors: questions every main arm got wrong
    qs = defaultdict(dict)
    for r in rows:
        if r["encoding"] in main_arms:
            qs[(r["type"], r["sub"], r["task"], r["question_id"])][r["encoding"]] = r
    floor = defaultdict(lambda: [0, 0])
    cases = []
    for (t, sub, task, qid), arms in qs.items():
        if len(arms) != len(main_arms):
            continue
        floor[(t, sub)][1] += 1
        if not any(r["correct"] for r in arms.values()):
            floor[(t, sub)][0] += 1
            cases.append((t, sub, task, qid, next(iter(arms.values()))["gold"]))
    out += ["### Floors: questions every arm got wrong", "",
            f"A question counts here when all of {', '.join(main_arms)} answered it wrong.", ""]
    subs_in_order = [(t, s) for t in TYPE_ORDER for s in sorted({k[1] for k in floor if k[0] == t})]
    out += table(["structure", "question", "wrong in every arm"],
                 [[t, s, f"{floor[(t, s)][0]} of {floor[(t, s)][1]}"] for t, s in subs_in_order])
    g = [(s, floor[("graph", s)]) for t, s in subs_in_order if t == "graph"]
    if g:
        out += ["On graphs the arms look level because the graph questions are near the floor, not because the "
                "encodings are at parity: " + "; ".join(f"`{s}` was wrong in every arm on {a} of {b}"
                                                         for s, (a, b) in g) + ".", ""]
    if cases:
        out += ["<details><summary>The cases (structure, question, gold)</summary>", ""]
        out += table(["structure", "question", "task", "id", "gold"],
                     [[t, s, task, qid, ", ".join(x) if isinstance(x, list) else str(x)]
                      for t, s, task, qid, x in sorted(cases)])
        out += ["</details>", ""]

    # 4. Paired discordance, ophanic@100 against each text arm
    if "ophanic@100" in encs:
        pair = {(r["task"], r["question_id"], r["encoding"]): r["correct"] for r in rows}
        out += ["### Paired: ophanic@100 against each text arm", "",
                "For the same structure and question: `o+ t−` counts calls ophanic@100 got right and the text arm "
                "got wrong; `o− t+` the reverse.", ""]
        body = []
        for t in TYPE_ORDER:
            keys = [(r["task"], r["question_id"]) for r in rows if r["encoding"] == "ophanic@100" and r["type"] == t]
            line = [t]
            for e in text_arms:
                ks = [k for k in keys if (*k, e) in pair]
                a = sum(pair[(*k, "ophanic@100")] and not pair[(*k, e)] for k in ks)
                b = sum(not pair[(*k, "ophanic@100")] and pair[(*k, e)] for k in ks)
                line.append(f"{a} / {b} (n={len(ks)})")
            body.append(line)
        out += table(["structure"] + [f"vs {e}: o+ t− / o− t+" for e in text_arms], body)

    # 5. Noise: the paired difference
    noisy = [r for r in rows if r["encoding"] == "ophanic-noise@100"]
    if noisy:
        clean_c = {(r["task"], r["question_id"]): r["correct"] for r in rows if r["encoding"] == "ophanic@100"}
        ks = [(r["task"], r["question_id"], r["correct"]) for r in noisy if (r["task"], r["question_id"]) in clean_c]
        n = len(ks)
        b = sum(c and not clean_c[(t, q)] for t, q, c in ks)      # noise right, clean wrong
        c_ = sum(not c and clean_c[(t, q)] for t, q, c in ks)     # clean right, noise wrong
        d = (b - c_) / n
        se = math.sqrt(max(b + c_ - (b - c_) ** 2 / n, 0)) / n
        clean_rows = [r for r in rows if r["encoding"] == "ophanic@100" and (r["task"], r["question_id"]) in
                      {(t, q) for t, q, _ in ks}]
        lo, hi = wilson(sum(r["correct"] for r in clean_rows), len(clean_rows))
        p = sum(r["correct"] for r in clean_rows) / len(clean_rows)
        half = max(p - lo, hi - p)
        out += ["### Noise: no detectable cost", "",
                f"No detectable cost, ±{100 * half:.0f} points. On {n} paired calls (ophanic-noise@100 against "
                f"ophanic@100 on the same structures and questions), noise minus clean is {100 * d:+.1f} points: "
                f"{b} calls flipped to right and {c_} to wrong. Each arm's own interval is about "
                f"±{100 * half:.0f} points, which can't resolve H4's 5-point threshold. The paired interval on the "
                f"difference is narrower (±{100 * 1.96 * se:.1f} points) because so few calls changed, but it "
                "assumes independent calls, and noise covered half the structures and one noise recipe.", ""]

    # 6. Token cost by structure type, against json (indent=2), compact json and list
    if tokens:
        tk = {(r["task"], r["question_id"], r["variant"]): r["prompt_eval_count"] for r in tokens
              if r.get("prompt_eval_count")}
        pec = {(r["task"], r["question_id"], r["encoding"]): r.get("prompt_eval_count") for r in rows}
        for (task, qid, v), c in tk.items():
            if v == "json-compact":
                pec[(task, qid, "json-compact")] = c
        meta = {(r["task"], r["question_id"]): r["type"] for r in rows}
        arms = [e for e in encs if "noise" not in e] + ["json-compact"]
        comps = [c for c in ("json", "json-compact", "list") if c in arms]

        def ratios(t, e, base, enc_only):
            vals = []
            for (task, qid), typ in meta.items():
                if typ != t:
                    continue
                x, y = pec.get((task, qid, e)), pec.get((task, qid, base))
                bare = tk.get((task, qid, "bare"))
                if not x or not y or (enc_only and not bare):
                    continue
                vals.append((x - bare) / (y - bare) if enc_only else x / y)
            return statistics.mean(vals) if vals else None

        out += ["### Input tokens by structure type, against three comparators", "",
                "The `all` row of the token table below is one average over an unweighted mix of types, against "
                "json pretty-printed with indent=2, the most expensive text arm. Here it is by type, against that "
                "json, against compact json (no whitespace; measured with qwen3:8b by `measure_tokens.py`, "
                "same template), and against the list. Ratios are means of paired per-call ratios.", "",
                "*Whole prompt* is `prompt_eval_count` as the model reports it, which includes the question, the "
                "instruction and the chat template and so pulls every ratio toward 1. *Encoding only* subtracts a "
                "measured prompt with the question and instruction alone (the `bare` rows in tokens.jsonl).", ""]
        for enc_only in (False, True):
            body = []
            for t in TYPE_ORDER:
                for e in arms:
                    cells = [ratios(t, e, base, enc_only) for base in comps]
                    body.append([t, e] + [f"{v:.2f}×" if v is not None else "—" for v in cells])
            out += [f"**{'Encoding only' if enc_only else 'Whole prompt'}** (qwen3:8b tokenizer)", ""]
            out += table(["structure", "encoding"] + [f"× {c}" for c in comps], body)
    return out


def report(run_dir: Path, rows: list[dict], label: str, tokens: list[dict] | None = None) -> str:
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
           f"- Each structure × size cell has {per_cell(rows)} structures, each asked 3 questions. The intervals "
           "treat every call as independent: they ignore that a structure's three questions are correlated and "
           "that the arms are paired on the same structures, so they are too narrow.",
           "- Overall and per-structure percentages mix questions at the floor (see Floors) with questions near "
           "the ceiling.",
           ""]

    out += review_checks(rows, encs, tokens or [])

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
    tok_path = run_dir / "tokens.jsonl"
    tokens = ([json.loads(x) for x in tok_path.read_text(encoding="utf-8").splitlines() if x.strip()]
              if tok_path.exists() else [])
    text = report(run_dir, rows, a.label, tokens)
    if a.notes:
        # the notes go after the header, before the first section
        head, rest = text.split("\n## ", 1)
        text = head + "\n" + Path(a.notes).read_text(encoding="utf-8").rstrip() + "\n\n## " + rest
    path = Path(a.report) if a.report else run_dir / "REPORT.md"
    path.write_text(text + "\n", encoding="utf-8")
    k = sum(r["correct"] for r in rows)
    print(f"{len(rows)} calls, {k} correct; wrote {path}")


if __name__ == "__main__":
    main()
