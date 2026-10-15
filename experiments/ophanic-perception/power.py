#!/usr/bin/env python3
"""
power.py: power of the pre-registered decision rules at the confirmatory size, by simulation (A4, A10).

    python power.py [--run results/pilot-qwen3-8b] [--sims 4000] [--seed 0]

The cluster is the structure. For each test it takes the per-structure paired differences (correct in the
ophanic arm minus correct in the comparator, averaged over the structure's paired questions) from a pilot run,
centres them at zero, and shifts them by a true difference δ. Each simulated confirmatory run resamples the
structures the design has for that test (40 per type × size cell), estimates the mean difference, and forms a 95%
interval from the cluster standard error (the normal approximation to the cluster bootstrap, close at n ≥ 40).
It then applies the decision rule score.py uses:

- H1a, H2 (A10): a difference "meets" the threshold when the estimate is at least 10 points and the interval's
  lower bound is above zero;
- H4 (A5, A10): noise "holds" when the whole interval lies within ±5 points.

The variance comes from one pilot model (qwen3:8b without thinking, pilot 1, 10 structures per cell); another model,
or a model nearer the ceiling, will differ. Deterministic for a seed.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score  # noqa: E402

PER_CELL = 40
TESTS = {
    # name: (description, arm a, arm b, row filter, structures in the confirmatory test)
    "H1a": ("layout spatial, medium size", "ophanic@100", "prose",
            lambda r: r["type"] == "layout" and r["kind"] == "spatial", PER_CELL),
    "H2": ("graph path, all sizes", "ophanic@100", "json",
           lambda r: r["type"] == "graph" and r["kind"] == "path", 3 * PER_CELL),
    "H4": ("noise minus clean, all structures", "ophanic-noise@100", "ophanic@100", lambda r: True, 9 * PER_CELL),
}


def per_structure(rows, a, b, keep):
    return [d / n for _, (d, n) in score.paired_clusters(rows, a, b, keep).values()]


def simulate(diffs, n, delta, rule, sims, rng):
    centred = [d - statistics.mean(diffs) + delta / 100 for d in diffs]
    hits = 0
    for _ in range(sims):
        x = [centred[rng.randrange(len(centred))] for _ in range(n)]
        est = statistics.mean(x)
        se = statistics.stdev(x) / math.sqrt(n)
        hits += rule(100 * est, 100 * (est - 1.96 * se), 100 * (est + 1.96 * se))
    return hits / sims


def meets(est, lo, hi):
    return est >= score.THRESHOLD and lo > 0


def within(est, lo, hi):
    return -score.EQUIV_MARGIN < lo and hi < score.EQUIV_MARGIN


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", default=str(HERE / "results" / "pilot-qwen3-8b"))
    ap.add_argument("--sims", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    rows, _ = score.load_all([Path(a.run)])
    rng = random.Random(a.seed)
    print(f"Power by simulation from {Path(a.run).name} ({a.sims} simulated runs per row, seed {a.seed})\n")
    for name, (desc, x, y, keep, n) in TESTS.items():
        diffs = per_structure(rows, x, y, keep)
        sd = statistics.stdev(diffs)
        print(f"{name} ({desc}; {x} − {y}): {len(diffs)} pilot structures, per-structure SD {100 * sd:.0f} points; "
              f"at {n} structures the standard error is about {100 * sd / math.sqrt(n):.1f} points")
        if name == "H4":
            for delta in (0, -2, -5):
                p = simulate(diffs, n, delta, within, a.sims, rng)
                print(f"  true difference {delta:+d}: P(interval within ±{score.EQUIV_MARGIN}) = {p:.2f}")
        else:
            for delta in (0, 10, 15, 20, 25, 30):
                p = simulate(diffs, n, delta, meets, a.sims, rng)
                print(f"  true difference {delta:+d}: P(meets: estimate ≥ {score.THRESHOLD} and lower bound > 0) "
                      f"= {p:.2f}")
        print()


if __name__ == "__main__":
    main()
