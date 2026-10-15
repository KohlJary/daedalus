#!/usr/bin/env python3
"""
score.py: score a run's calls and write its report (see DESIGN.md).

    python score.py results/<run> [--report REPORT-pilot.md] [--label PILOT] [--notes results/<run>/notes.md]
        [--primary ophanic@100] [--boot 2000] [--boot-seed 0]

Normalises answers (case, whitespace, markdown, trailing punctuation, list order for set answers),
applies the ±5-point tolerance to proportions, and reports accuracy per cell with a Wilson 95% interval.

It also writes the pre-registered statistics of DESIGN.md's amendments (proposed, Kohl to confirm): a cluster
bootstrap over structures for every paired arm difference (A4), H1 split into spatial and proportion (A1), H3 as
the slope of ophanic's advantage over the better of prose and list (A4), H4 against a 5-point equivalence margin
(A5), H5 by structure type against compact json then list (A6), and H6 marked not run (A9). In a run labelled
PILOT these are printed without readings: a pilot tests nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOLERANCE = 5
ENC_ORDER = ["ophanic@100", "ophanic@60", "ophanic-noise@100", "ophanic-noise@60", "prose", "json", "json-compact",
             "list", "list-lookup"]
MOD_ORDER = ["", "fenced", "unframed", "fenced+unframed"]
TYPE_ORDER = ["layout", "graph", "containment"]
SIZE_ORDER = ["small", "medium", "large"]
THRESHOLD = 10        # H1, H2: points
EQUIV_MARGIN = 5      # H4 (A5): points
COST_RATIO = 1.5      # H5
# A2: in these drawings most graph edges are listed, not drawn, so the ophanic graph arm is relabelled
GRAPH_ARM = "partial-edge list plus picture"
SHARE_PAIR = "ophanic@60"   # generate.SHARE_PAIR: the drawing whose widths the text arms state


def enc_key(e: str):
    base, *mods = e.split("+")
    m = "+".join(sorted(mods))
    return (ENC_ORDER.index(base) if base in ENC_ORDER else len(ENC_ORDER), base,
            MOD_ORDER.index(m) if m in MOD_ORDER else len(MOD_ORDER), m)


def tl(t: str) -> str:
    """A structure type as reports label it: the graph rows carry A2's relabel of the ophanic arm."""
    return f"graph (ophanic arm: {GRAPH_ARM})" if t == "graph" else t


def clean_partner(noise_arm: str) -> str:
    """ophanic-noise@100+fenced -> ophanic@100+fenced"""
    return noise_arm.replace("ophanic-noise@", "ophanic@", 1)


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


def load_all(run_dirs) -> tuple[list[dict], list[dict]]:
    """(scored rows, error rows) over one or more run directories. A row with an error (including a call that
    gave no answer) is never scored."""
    rows, errors = [], []
    for d in run_dirs:
        with (Path(d) / "calls.jsonl").open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("error"):
                    errors.append(r)
                else:
                    r["correct"] = correct(r, r["answer"])
                    rows.append(r)
    return rows, errors


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
    main_arms = [e for e in encs if "noise" not in e and not e.startswith("list-lookup")]
    text_arms = [e for e in ("prose", "json", "list") if e in encs]
    by = defaultdict(list)
    for r in rows:
        by[(r["encoding"], r["type"], r["kind"])].append(r)
        by[(r["encoding"], r["type"], r["sub"])].append(r)
    out = ["## Checks from the pilot review", "",
           "Computed by score.py from calls.jsonl (and tokens.jsonl for the cost table), at Momus's request. "
           "Like everything else here, these are descriptive.", ""]

    # 1. Layout: spatial vs proportion
    widths = any(r.get("harness", 1) >= 2 for r in rows if r["type"] == "layout")
    out += ["### Layout: spatial questions versus the proportion question", "",
            "Spatial is `right_of` plus `below`; proportion is `share`. "
            + ("Every arm has to compute the share (A1): the prose, json and list encodings state character "
               "widths (\"24 of 59 characters\"), and the ophanic encodings draw them." if widths else
               "In the prose, json and list encodings the share is written down as a number, so for them the "
               "question is a lookup; in the ophanic encodings it has to be measured from character widths."), ""]
    out += table(["encoding", "layout spatial", "layout proportion"],
                 [[e, kn(by[(e, "layout", "spatial")]), kn(by[(e, "layout", "proportion")])] for e in encs])
    oph = by[("ophanic@100", "layout", "spatial")]
    txt = [sum(r["correct"] for r in by[(e, "layout", "spatial")]) for e in text_arms]
    if oph and txt and not widths:
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
                 [[tl(t), s, f"{floor[(t, s)][0]} of {floor[(t, s)][1]}"] for t, s in subs_in_order])
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
            line[0] = tl(t)
            body.append(line)
        out += table(["structure"] + [f"vs {e}: o+ t− / o− t+" for e in text_arms], body)

    # 5. Noise: the paired difference
    noise_arm = next((e for e in encs if e.startswith("ophanic-noise@100")), None)
    noisy = [r for r in rows if r["encoding"] == noise_arm]
    if noisy:
        partner = clean_partner(noise_arm)
        clean_c = {(r["task"], r["question_id"]): r["correct"] for r in rows if r["encoding"] == partner}
        ks = [(r["task"], r["question_id"], r["correct"]) for r in noisy if (r["task"], r["question_id"]) in clean_c]
        n = len(ks)
        b = sum(c and not clean_c[(t, q)] for t, q, c in ks)      # noise right, clean wrong
        c_ = sum(not c and clean_c[(t, q)] for t, q, c in ks)     # clean right, noise wrong
        d = (b - c_) / n
        se = math.sqrt(max(b + c_ - (b - c_) ** 2 / n, 0)) / n
        clean_rows = [r for r in rows if r["encoding"] == partner and (r["task"], r["question_id"]) in
                      {(t, q) for t, q, _ in ks}]
        lo, hi = wilson(sum(r["correct"] for r in clean_rows), len(clean_rows))
        p = sum(r["correct"] for r in clean_rows) / len(clean_rows)
        half = max(p - lo, hi - p)
        share_noisy = len({r["task"] for r in noisy}) / max(1, len({r["task"] for r in rows}))
        out += ["### Noise: the paired difference", "",
                f"On {n} paired calls ({noise_arm} against {partner} on the same structures and questions), noise "
                f"minus clean is {100 * d:+.1f} points: {b} calls flipped to right and {c_} to wrong. Each arm's own "
                f"interval is about ±{100 * half:.0f} points. The naive paired interval on the difference is "
                f"±{100 * 1.96 * se:.1f} points, but it assumes independent calls; the cluster-bootstrap interval "
                f"under Hypotheses (H4) is the one to read. Noise covered {100 * share_noisy:.0f}% of the "
                "structures, with one noise recipe.", ""]

    # 6. Token cost by structure type, against json (indent=2), compact json and list
    if tokens:
        tk = {(r["task"], r["question_id"], r["variant"]): r["prompt_eval_count"] for r in tokens
              if r.get("prompt_eval_count")}
        pec = {(r["task"], r["question_id"], r["encoding"]): r.get("prompt_eval_count") for r in rows}
        for (task, qid, v), c in tk.items():
            if v != "bare":   # measured unframed prompts take precedence over the (possibly framed) calls
                pec[(task, qid, v)] = c
        meta = {(r["task"], r["question_id"]): r["type"] for r in rows}
        arms = [e for e in encs if "noise" not in e and "+" not in e and e != "json-compact"] + ["json-compact"]
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
                "json, against compact json (no whitespace; measured by `measure_tokens.py`, same template), and "
                "against the list. Ratios are means of paired per-call ratios. Where `measure_tokens.py` measured "
                "an arm's unframed prompt, that count is used; otherwise the call's own count.", "",
                "*Whole prompt* is `prompt_eval_count` as the model reports it, which includes the question, the "
                "instruction and the chat template and so pulls every ratio toward 1. *Encoding only* subtracts a "
                "measured prompt with the question and instruction alone (the `bare` rows in tokens.jsonl).", ""]
        for enc_only in (False, True):
            body = []
            for t in TYPE_ORDER:
                for e in arms:
                    cells = [ratios(t, e, base, enc_only) for base in comps]
                    body.append([tl(t), e] + [f"{v:.2f}×" if v is not None else "—" for v in cells])
            tok_models = ", ".join(sorted({r["model"] for r in tokens})) or "?"
            out += [f"**{'Encoding only' if enc_only else 'Whole prompt'}** ({tok_models} tokenizer)", ""]
            out += table(["structure", "encoding"] + [f"× {c}" for c in comps], body)
    return out


# ---------------------------------------------------------------------------------------------------------
# Cluster bootstrap over structures (A4) and the pre-registered hypothesis statistics
# ---------------------------------------------------------------------------------------------------------

def bootstrap(clusters: dict, stat, B: int = 2000, seed: int = 0):
    """Percentile 95% interval for stat() under a cluster bootstrap.

    `clusters` maps a cluster id (a structure) to (stratum, payload). Each replicate resamples cluster ids with
    replacement within each stratum (the design's type × size cells), keeping each structure's arms and questions
    together, and passes the payloads to stat(), which returns a number or None. Deterministic for a given seed.
    Returns (point, lo, hi), or None if there are no clusters."""
    if not clusters:
        return None
    rng = random.Random(seed)
    strata = defaultdict(list)
    for cid in sorted(clusters):
        strata[clusters[cid][0]].append(cid)
    point = stat([clusters[c][1] for c in sorted(clusters)])
    if point is None:
        return None
    reps = []
    for _ in range(B):
        sample = []
        for st in sorted(strata):
            ids = strata[st]
            sample += [clusters[ids[rng.randrange(len(ids))]][1] for _ in ids]
        v = stat(sample)
        if v is not None:
            reps.append(v)
    reps.sort()
    lo = reps[int(0.025 * (len(reps) - 1))]
    hi = reps[int(math.ceil(0.975 * (len(reps) - 1)))]
    return point, lo, hi


def condition(r) -> str:
    """A model and its thinking status, which together are the unit of analysis (A8 revision): conditions are
    reported and tested separately, never pooled."""
    return r["model"] + (" (thinking)" if r.get("think") else "")


def pkey(r):
    return (r["task"], r["question_id"], condition(r))


def paired_clusters(rows, a, b, keep=lambda r: True):
    """Per structure: (stratum, (sum of correct_a − correct_b, n pairs)) over calls paired on question and model."""
    other = {pkey(r): r["correct"] for r in rows if r["encoding"] == b and keep(r)}
    out = {}
    for r in rows:
        if r["encoding"] != a or not keep(r) or pkey(r) not in other:
            continue
        st, (d, n) = out.get(r["task"], ((r["type"], r["size"]), (0, 0)))
        out[r["task"]] = (st, (d + int(r["correct"]) - int(other[pkey(r)]), n + 1))
    return out


def mean_diff(payloads):
    n = sum(p[1] for p in payloads)
    return 100 * sum(p[0] for p in payloads) / n if n else None


def paired_diff(rows, a, b, keep=lambda r: True, B=2000, seed=0):
    """(point, lo, hi, structures, pairs) for accuracy(a) − accuracy(b) in points, or None."""
    cl = paired_clusters(rows, a, b, keep)
    res = bootstrap(cl, mean_diff, B, seed)
    if res is None:
        return None
    return (*res, len(cl), sum(p[1][1] for p in cl.values()))


def slope_clusters(rows, oph, others, keep):
    """H3: per structure, (size, (k_ophanic, k_other1, k_other2, ..., n)) on questions answered in every arm."""
    arms = [oph, *others]
    got = defaultdict(dict)
    for r in rows:
        if r["encoding"] in arms and keep(r):
            got[pkey(r)][r["encoding"]] = (r["correct"], r["size"])
    out = {}
    for k, by in got.items():
        if len(by) != len(arms):
            continue
        size = by[oph][1]
        _, prev = out.get(k[0], (size, [0] * (len(arms) + 1)))
        prev = [p + int(by[e][0]) for p, e in zip(prev, arms)] + [prev[-1] + 1]
        out[k[0]] = (size, prev)
    return out


def slope_stat(payloads_with_size):
    """(large advantage − small advantage), where advantage = ophanic − the better of the other arms, in points."""
    sums = {}
    for size, p in payloads_with_size:
        acc = sums.setdefault(size, [0] * len(p))
        for i, v in enumerate(p):
            acc[i] += v
    if "small" not in sums or "large" not in sums:
        return None

    def adv(v):
        return (v[0] - max(v[1:-1])) / v[-1]
    return 100 * (adv(sums["large"]) - adv(sums["small"]))


def slope(rows, oph, others, keep, B=2000, seed=0):
    cl = slope_clusters(rows, oph, others, keep)
    # keep the size with the payload so the statistic can split by it
    res = bootstrap({k: (st, (st, p)) for k, (st, p) in cl.items()}, slope_stat, B, seed)
    if res is None:
        return None
    by_size = {}
    for size in SIZE_ORDER:
        ps = [p for st, p in cl.values() if st == size]
        if ps:
            tot = [sum(x) for x in zip(*ps)]
            by_size[size] = 100 * (tot[0] - max(tot[1:-1])) / tot[-1]
    return (*res, len(cl), by_size)


def fmt_ci(res, unit=" points"):
    if res is None:
        return "—"
    return f"{res[0]:+.1f}{unit} (95% CI {res[1]:+.1f} to {res[2]:+.1f}; {res[3]} structures, {res[4]} pairs)"


def hypotheses(rows: list[dict], encs: list[str], tokens: list[dict], label: str, primary: str = "ophanic@100",
               B: int = 2000, seed: int = 0) -> list[str]:
    pilot = "PILOT" in label.upper()
    have = set(encs)
    out = ["## Hypotheses: the pre-registered statistics (amendments A1-A9, proposed, Kohl to confirm)", ""]
    if pilot:
        out += [f"**{label}: these numbers test nothing.** They are printed to check that the statistics run, with "
                "no reading against any threshold. Intervals are percentile 95% intervals from a cluster bootstrap "
                f"over structures ({B} replicates, seed {seed}), resampling within each type × size cell and keeping "
                "each structure's arms, questions and models together.", ""]
    else:
        out += [f"Intervals are percentile 95% intervals from a cluster bootstrap over structures ({B} replicates, "
                f"seed {seed}), resampling within each type × size cell and keeping each structure's arms and "
                "questions together. Each section is one model and thinking condition; conditions are never "
                "pooled.", ""]
    conds = sorted({condition(r) for r in rows})
    if len(conds) > 1:
        raise ValueError(f"hypotheses() takes one model and thinking condition, got {conds}")
    out += [f"The ophanic arm tested is `{primary}`.", ""]
    if primary not in have:
        return out + [f"`{primary}` is not in this run, so no hypothesis statistic is computed.", ""]

    def reading(ok, txt_ok, txt_no):
        return "" if pilot else f" **Reading: {txt_ok if ok else txt_no}.**"

    def beats(res):
        return res is not None and res[0] >= THRESHOLD and res[1] > 0

    # H1a, H1b (A1). H1b pairs the text arms with the drawing whose widths they state (SHARE_PAIR, ophanic@60)
    mods = primary.split("+")[1:]
    share_arm = "+".join([SHARE_PAIR, *mods])
    if share_arm not in have:
        share_arm = primary
    for name, kind, desc, arm in (("H1a", "spatial", "layout `right_of` and `below`", primary),
                                  ("H1b", "proportion", "layout `share`", share_arm)):
        keep = (lambda k: lambda r: r["type"] == "layout" and r["size"] == "medium" and r["kind"] == k)(kind)
        res = {b: paired_diff(rows, arm, b, keep, B, seed) for b in ("prose", "list") if b in have}
        note = ""
        if kind == "proportion":
            note = (f" The text arms state the widths {SHARE_PAIR} draws, so H1b pairs them with `{arm}`."
                    if arm.startswith(SHARE_PAIR) else
                    f" `{SHARE_PAIR}`, whose widths the text arms state, is not in this run: `{arm}` stands in, "
                    "and its widths differ from the stated ones.")
        out += [f"**{name}** ({desc}, medium size): {arm} minus each text arm.{note}", ""]
        out += [f"- vs {b}: {fmt_ci(v)}" for b, v in res.items()]
        if res:
            ok = all(beats(v) for v in res.values()) and len(res) == 2
            out[-1] += reading(ok, f"ophanic beats both by at least {THRESHOLD} points", "falsified as written "
                               f"(not ahead of both by {THRESHOLD} points with an interval above zero)")
        if kind == "proportion":
            golds = [float(r["gold"]) for r in rows if r["encoding"] == primary and r["sub"] == "share"
                     and r["size"] == "medium"]
            if golds:
                hits = {c: sum(abs(c - g) <= TOLERANCE for g in golds) for c in range(0, 101)}
                c = max(hits, key=lambda x: (hits[x], -abs(x - 25)))
                acc = {e: [r["correct"] for r in rows if r["encoding"] == e and r["sub"] == "share"
                           and r["size"] == "medium"] for e in (arm, "prose", "json", "list", "list-lookup")
                       if e in have}
                out += [f"- Constant-guess baseline: always answering {c} scores {hits[c]}/{len(golds)} = "
                        f"{100 * hits[c] / len(golds):.0f}% on these questions. Accuracy: "
                        + ", ".join(f"{e} {100 * sum(v) / len(v):.0f}%" for e, v in acc.items() if v) + "."]
                if "list-lookup" in have:
                    out += ["- `list-lookup` is the lookup ceiling (A12): the same question with the percentage "
                            "stated. It is a control, never a comparator in a test."]
        out += [""]

    # H2 (A2)
    keep = lambda r: r["type"] == "graph" and r["kind"] == "path"
    res = {b: paired_diff(rows, primary, b, keep, B, seed) for b in ("json", "list") if b in have}
    out += [f"**H2** (graph `reach` and `path_length`, all sizes): {primary}, here a {GRAPH_ARM} (A2), minus "
            "json and list.", ""]
    out += [f"- vs {b}: {fmt_ci(v)}" for b, v in res.items()]
    if res:
        ok = not (all(beats(v) for v in res.values()) and len(res) == 2)
        out[-1] += reading(ok, "not falsified (no 10-point lead over both)", "falsified (ahead of both by 10 points)")
    out += [""]

    # H3 (A4): slope of the advantage over the better of prose and list
    others = [b for b in ("prose", "list") if b in have]
    if others:
        out += [f"**H3** (layout): advantage = {primary} minus the better of {' and '.join(others)} at each size; "
                "the statistic is large advantage minus small advantage.", ""]
        for nm, keep in (("all layout questions", lambda r: r["type"] == "layout"),
                         ("spatial only", lambda r: r["type"] == "layout" and r["kind"] == "spatial")):
            res = slope(rows, primary, others, keep, B, seed)
            if res is None:
                out += [f"- {nm}: —"]
                continue
            sizes = ", ".join(f"{s} {v:+.1f}" for s, v in res[4].items())
            line = (f"- {nm}: {res[0]:+.1f} points (95% CI {res[1]:+.1f} to {res[2]:+.1f}; {res[3]} structures); "
                    f"advantage by size: {sizes}.")
            if nm == "all layout questions":
                line += reading(res[1] > 0, "grows with size (interval above zero)",
                                "falsified (shrinks or reverses)" if res[0] < 0 else "not shown (interval includes zero)")
            out += [line]
        out += [""]

    # H4 (A5): noise, equivalence margin
    noise = next((e for e in encs if e.startswith("ophanic-noise@") and clean_partner(e) == primary), None)
    out += [f"**H4** (noise, A5): noisy minus clean, against a ±{EQUIV_MARGIN}-point equivalence margin.", ""]
    if noise:
        res = paired_diff(rows, noise, primary, B=B, seed=seed)
        cover = len({r["task"] for r in rows if r["encoding"] == noise}) / max(1, len({r["task"] for r in rows
                                                                                       if r["encoding"] == primary}))
        line = f"- {noise} minus {primary}: {fmt_ci(res)}; noise on {100 * cover:.0f}% of the structures."
        if res and not pilot:
            if -EQUIV_MARGIN < res[1] and res[2] < EQUIV_MARGIN:
                line += f" **Reading: holds (the interval lies within ±{EQUIV_MARGIN}).**"
            elif res[2] <= -EQUIV_MARGIN:
                line += f" **Reading: falsified (costs {EQUIV_MARGIN} points or more).**"
            else:
                line += " **Reading: unresolved (the interval is wider than the margin).**"
        out += [line, ""]
    else:
        out += [f"- No noise arm paired with {primary} in this run.", ""]

    # H5 (A6): cost, encoding-only, by type
    base = primary.split("+")[0]
    tk = {(r["task"], r["question_id"], r["variant"]): r["prompt_eval_count"] for r in tokens
          if r.get("prompt_eval_count")}
    for r in rows:   # an unframed, unmodified call is the same prompt measure_tokens.py sends
        k = (r["task"], r["question_id"], r["encoding"])
        if r.get("framing") in (None, False, "off") and "+" not in r["encoding"] and r.get("prompt_eval_count") and k not in tk:
            tk[k] = r["prompt_eval_count"]
    out += [f"**H5** (cost, A6): encoding-only input tokens (each model's own count minus a bare question prompt, "
            f"unframed), mean of paired per-question ratios by structure type. Primary comparator compact json, "
            f"then list; indented json for continuity. Threshold {COST_RATIO}× compact json.", ""]
    if any(v == base for (_, _, v) in tk):
        meta = {r["task"]: (r["type"], r["size"]) for r in rows}
        body = []
        for t in TYPE_ORDER:
            line = [tl(t)]
            for comp in ("json-compact", "list", "json"):
                cl = {}
                for (task, qid, v), x in tk.items():
                    if v != base or meta.get(task, ("",))[0] != t:
                        continue
                    y, bare = tk.get((task, qid, comp)), tk.get((task, qid, "bare"))
                    if y and bare and y > bare:
                        st, prev = cl.get(task, (meta[task], []))
                        cl[task] = (st, prev + [(x - bare) / (y - bare)])
                res = bootstrap(cl, lambda ps: statistics.mean(v for p in ps for v in p) if ps else None, B, seed)
                cell_ = "—" if res is None else f"{res[0]:.2f}× ({res[1]:.2f}–{res[2]:.2f})"
                if comp == "json-compact" and res and not pilot:
                    cell_ += " ≥1.5" if res[1] >= COST_RATIO else " <1.5" if res[2] < COST_RATIO else " ~1.5"
                line.append(cell_)
            body.append(line)
        out += table(["structure", f"{base} × json-compact", f"{base} × list", f"{base} × json (indented)"], body)
    else:
        out += [f"- No `measure_tokens.py` counts for `{base}` in tokens.jsonl: run it to fill this in.", ""]

    out += ["**H6** (construction): **not run.** It is not built, so it is not part of any run until it is built "
            "and reviewed (A9).", ""]
    return out


def report(run_dir: Path, rows: list[dict], label: str, tokens: list[dict] | None = None,
           primary: str = "ophanic@100", B: int = 2000, seed: int = 0, errors: list[dict] | None = None) -> str:
    if errors is None:
        errors = [r for r in load_all([run_dir])[1]]
    conds = sorted({condition(r) for r in rows} | {condition(r) for r in errors})
    if len(conds) > 1:
        # One full report per model and thinking condition, never pooled (A8 revision)
        out = [f"# {label}: no hypothesis tested" if "PILOT" in label.upper() else f"# {label}", "",
               f"This run holds {len(conds)} model and thinking conditions: {', '.join(conds)}. Each is reported "
               "and tested on its own below; no number pools them.", ""]
        for c in conds:
            sub = report(run_dir, [r for r in rows if condition(r) == c], label,
                         [t for t in (tokens or []) if t.get("model") == c.split(" (")[0]], primary, B, seed,
                         [r for r in errors if condition(r) == c])
            body = sub.split("\n", 1)[1]
            out += [f"# Condition: {c}", ""] + ["#" + x if x.startswith("#") else x for x in body.splitlines()]
        return "\n".join(out)
    encs = sorted({r["encoding"] for r in rows}, key=enc_key)
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
           f"- Run: `{run_dir.name}`{' and others' if len({r['run'] for r in rows if 'run' in r}) > 1 else ''}; condition: {', '.join(conds)}; tasks: {', '.join(tasks_files)}",
           f"- Calls scored: {len(rows)}; num_ctx: {num_ctx}",
           f"- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±{TOLERANCE} points.",
           f"- Each structure × size cell has {per_cell(rows)} structures, each asked 3 questions. The intervals "
           "treat every call as independent: they ignore that a structure's three questions are correlated and "
           "that the arms are paired on the same structures, so they are too narrow.",
           "- Overall and per-structure percentages mix questions at the floor (see Floors) with questions near "
           "the ceiling.",
           ""]

    out += hypotheses(rows, encs, tokens or [], label, primary, B, seed)
    out += review_checks(rows, encs, tokens or [])


    out += ["## Accuracy by encoding", ""]
    out += table(["encoding", "accuracy"], [[e, cell(group[(e,)])] for e in encs])

    out += ["## Encoding × structure", ""]
    out += table(["structure"] + encs, [[tl(t)] + [cell(group[(e, t)]) for e in encs] for t in TYPE_ORDER])

    out += ["## Encoding × structure × size", ""]
    out += table(["structure", "size"] + encs,
                 [[tl(t), s] + [cell(group[(e, t, s)]) for e in encs] for t in TYPE_ORDER for s in SIZE_ORDER])

    subs = {t: sorted({r["sub"] for r in rows if r["type"] == t}) for t in TYPE_ORDER}
    kind_of = {r["sub"]: r["kind"] for r in rows}
    out += ["## Encoding × structure × question kind", ""]
    out += table(["structure", "question (kind)"] + encs,
                 [[tl(t), f"{q} ({kind_of[q]})"] + [cell(group[(e, t, q)]) for e in encs]
                  for t in TYPE_ORDER for q in subs[t]])

    # Noise, on the structures that have a noise call, paired
    noise_arm = next((e for e in encs if e.startswith("ophanic-noise@100")), None)
    noisy = {(r["task"], r["question_id"]) for r in rows if r["encoding"] == noise_arm}
    if noisy:
        partner = clean_partner(noise_arm)
        clean_rows = [r for r in rows if r["encoding"] == partner and (r["task"], r["question_id"]) in noisy]
        noise_rows = [r for r in rows if r["encoding"] == noise_arm]
        out += ["## Noise (paired: the same structures and questions)", ""]
        out += table(["structure", partner, noise_arm],
                     [[tl(t), cell([r for r in clean_rows if r["type"] == t]), cell([r for r in noise_rows if r["type"] == t])]
                      for t in TYPE_ORDER] + [["all", cell(clean_rows), cell(noise_rows)]])

    out += ["## Input tokens per encoding", "",
            "Mean `prompt_eval_count` reported by the model API per call (the prompt as sent: the framing sentence "
            "when framing is on, the encoding, the question and instruction, under the model's chat template). The ratio is the mean of each call's count over the json call for the same structure and question.", ""]
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
            line = [tl(t), s]
            for e in encs:
                v, rv = tok.get((e, t, s)), ratio.get((e, t, s))
                line.append(f"{statistics.mean(v):.0f}" + (f" ({statistics.mean(rv):.2f}×)" if rv else "") if v else "—")
            body.append(line)
    body.append(["all", ""] + [f"({statistics.mean(ratio[(e,)]):.2f}×)" if ratio.get((e,)) else "—" for e in encs])
    out += table(["structure", "size"] + encs, body)

    out += ["## Harness checks", ""]
    n_err = len(errors)
    err_by = defaultdict(int)
    for r in errors:
        err_by[(r["encoding"], r.get("sub", "?"))] += 1
    empty = sum(1 for r in rows if not clean(r["answer"]))
    trunc = sum(1 for r in rows if r.get("prompt_eval_count") and r.get("num_ctx")
                and r["prompt_eval_count"] >= r["num_ctx"] - 8)
    long_answers = sum(1 for r in rows if len(clean(r["answer"])) > 200)
    cut = sum(1 for r in rows if r.get("done_reason") in ("length", "max_tokens"))
    stopped = [r for r in rows if r.get("done_reason") is not None]
    settings = sorted({(r.get("harness", 1), r.get("framing", False), repr(r.get("stop")), r.get("max_tokens"),
                        r.get("think", False)) for r in rows})
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    out += [f"- Calls with an error (left out of scoring; a call with no answer is one): {n_err}"
            + (" — " + ", ".join(f"{e} {q} ×{n}" for (e, q), n in sorted(err_by.items())) if err_by else ""),
            f"- Empty answers: {empty}",
            f"- Prompts at or over num_ctx (would be truncated): {trunc}",
            f"- Answers over 200 characters: {long_answers}",
            f"- Answers cut off by the token limit: {cut}" + ("" if stopped else " (done_reason not recorded)"),
            "- Settings (harness, framing, stop, max tokens, think): "
            + "; ".join(f"{h}, {fr}, {st}, {m}, {th}" for h, f, st, m, th in settings
                        for fr in [{True: "pilot2", False: "off", None: "off"}.get(f, f)]),
            f"- Latency: total {sum(lat) / 60:.1f} min, median {statistics.median(lat):.2f} s, "
            f"max {max(lat):.1f} s" if lat else "- Latency: —", ""]
    out += ["## All cells", ""]
    out += table(["structure", "size", "question"] + encs,
                 [[tl(t), s, q] + [cell(group[(e, t, s, q)]) for e in encs]
                  for t in TYPE_ORDER for s in SIZE_ORDER for q in subs[t]])
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir", nargs="+", help="one or more results/<run> directories, reported per condition")
    ap.add_argument("--report", default=None, help="output path (default: <run_dir>/REPORT.md)")
    ap.add_argument("--label", default="PILOT")
    ap.add_argument("--notes", default=None, help="a Markdown file of hand-written findings, inserted after the header")
    ap.add_argument("--primary", default="ophanic@100", help="the ophanic arm the hypotheses test")
    ap.add_argument("--boot", type=int, default=2000, help="bootstrap replicates")
    ap.add_argument("--boot-seed", type=int, default=0)
    a = ap.parse_args(argv)
    run_dirs = [Path(d) for d in a.run_dir]
    run_dir = run_dirs[0]
    rows, errors = load_all(run_dirs)
    tokens = []
    for d in run_dirs:
        tok_path = d / "tokens.jsonl"
        if tok_path.exists():
            tokens += [json.loads(x) for x in tok_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    text = report(run_dir, rows, a.label, tokens, a.primary, a.boot, a.boot_seed, errors)
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
