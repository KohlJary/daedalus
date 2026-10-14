"""Deterministic repro for gameplan T-e14: escalated conflicts are never recorded, so incompatible diffs merge.
No model: handwritten diffs, a stub judge that approves everything, the real verifier and orchestrator.

  python3 make_ariadne_src.py && python3 repro_conflict_escalation.py

Expected with the bug: both cases report detected=1, stored_on_bus=0; the different-line case commits both
diffs (add() now rejects negatives while the new sum_all() relies on it accepting them)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp, feature
from daedalus.ariadne.diff_bus import AriadneBus, Diff
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.semantic_review import SemanticReviewResult, ReviewVerdict


class ApproveAll:
    def review(self, diff, intent, verification=None):
        return SemanticReviewResult(diff_id=diff.id, verdict=ReviewVerdict.APPROVED, reasoning="stub", reviewer="stub")


CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
TESTS = {"tests/test_calc.py": "from calc import add, mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"}


def diff_of(new_calc):
    w = exp.make_repo({"calc.py": CALC, **TESTS})
    (w / "calc.py").write_text(new_calc)
    return exp.harness_diff(w)


def trial(label, calc_a, calc_b):
    repo = exp.make_repo({"calc.py": CALC, **TESTS})
    exp.git(repo, "config", "user.email", "t@t")
    exp.git(repo, "config", "user.name", "t")
    bus = AriadneBus(root=Path(tempfile.mkdtemp()) / "b")
    bus.initialize()
    for i, c in enumerate((calc_a, calc_b)):
        bus.submit_diff(Diff.from_git_diff(work_id=f"w{i}", instance_id="i", diff_content=diff_of(c), description=f"package {i}"))
    orch = AriadneOrchestrator(repo, bus=bus, auto_commit=True, autonomy="full", semantic_reviewer=ApproveAll())
    orch.verifier = feature.real_verifier(repo)
    o = orch.process_pending()
    print(f"{label}: detected={o.conflicts_detected} resolved={o.conflicts_resolved} stored_on_bus={len(bus.list_conflicts())} "
          f"commits={o.commits_created} errors={[e[:80] for e in o.errors]}")
    print("   main calc.py:", repr(exp.git(repo, "show", "HEAD:calc.py").stdout))
    return o


if __name__ == "__main__":
    trial("same-line conflict",
          CALC.replace("    return a * b", "    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):\n        raise TypeError('numbers only')\n    return a * b"),
          CALC.replace("    return a * b", "    if isinstance(a, str) or isinstance(b, str):\n        return a * b\n    return a * b"))
    o = trial("different-line conflict",
              CALC.replace("def add(a, b):\n    return a + b", "def add(a, b):\n    if a < 0 or b < 0:\n        raise ValueError('no negatives')\n    return a + b"),
              CALC + "\n\ndef sum_all(xs):\n    \"\"\"Sum a list of numbers, negatives included.\"\"\"\n    total = 0\n    for x in xs:\n        total = add(total, x)\n    return total\n")
    sys.exit(1 if o.commits_created else 0)  # non-zero while the bug is present
