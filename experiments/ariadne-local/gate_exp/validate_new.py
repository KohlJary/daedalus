"""Validate the new tickets' oracles before any run."""
import shutil, sys
sys.path.insert(0, ".")
import exp
from tasks_new import NEW_TASKS, REPORT, SHIPPING

def diff_for(task, changes):
    repo = exp.make_repo(task["files"])
    for rel, content in changes.items():
        (repo / rel).write_text(content)
    d = exp.harness_diff(repo); shutil.rmtree(repo.parent); return d

def check(task, src):
    """Run an arbitrary oracle source against a diff."""
    t = dict(task, oracle=src)
    return lambda d: exp.oracle(t, d)["oracle_pass"]

REPORT_REF = '''def _totals(orders):
    totals = {}
    for o in orders:
        if o["status"] != "refunded":
            totals[o["customer"]] = totals.get(o["customer"], 0) + o["amount"]
    return totals


def _line(label, amount):
    return f"{label:<12}{amount:>10.2f}"


def build_report(orders):
    totals = _totals(orders)
    lines = [_line(c, totals[c]) for c in sorted(totals, key=lambda c: (-totals[c], c))]
    pending = sum(o["amount"] for o in orders if o["status"] == "pending")
    lines += ["-" * 22, _line("TOTAL", sum(totals.values()))]
    if pending:
        lines.append(_line("(pending)", pending))
    return "\\n".join(lines)
'''
REPORT_BAD = REPORT_REF.replace('key=lambda c: (-totals[c], c)', 'key=lambda c: -totals[c]')  # ties no longer by name
SHIP_REF = '''BRACKETS = {
    "domestic": [(1, 5.0), (5, 9.5), (20, 18.0)],
    "international": [(1, 15.0), (5, 27.0)],
}
OVER = {"domestic": (20, 18.0, 0.75), "international": (5, 27.0, 2.5)}


def shipping_cost(weight, zone):
    if weight <= 0:
        raise ValueError("weight must be positive")
    if zone not in BRACKETS:
        raise ValueError(f"unknown zone: {zone}")
    for limit, cost in BRACKETS[zone]:
        if weight <= limit:
            return round(cost, 2)
    start, base, per = OVER[zone]
    return round(base + (weight - start) * per, 2)
'''
SHIP_BAD = SHIP_REF.replace("if weight <= limit:", "if weight < limit:")  # boundary regression
ok = True
for name, (ref, bad, path) in {"refactor_report": (REPORT_REF, REPORT_BAD, "report.py"),
                               "refactor_shipping": (SHIP_REF, SHIP_BAD, "shipping.py")}.items():
    t = NEW_TASKS[name]
    base = exp.oracle(t, "")["oracle_pass"]
    r = exp.oracle(t, diff_for(t, {path: ref}))
    b = exp.oracle(t, diff_for(t, {path: bad}))["oracle_pass"]
    good = base and r["oracle_pass"] and not b
    ok &= good
    print(f"{name:18} original passes={base} reference passes={r['oracle_pass']} regression caught={not b} {'' if good else r['oracle_out']}")

AMB = {"ambiguous_average": ("stats.py", {
           "returns_zero": "def average(xs):\n    if not xs:\n        return 0\n    return sum(xs) / len(xs)\n",
           "returns_none": "def average(xs):\n    if not xs:\n        return None\n    return sum(xs) / len(xs)\n",
           "raises_valueerror": "def average(xs):\n    if not xs:\n        raise ValueError('empty')\n    return sum(xs) / len(xs)\n"}),
       "ambiguous_truncate": ("text.py", {
           "within_n_dots": "def truncate(text, n):\n    return text if len(text) <= n else text[:n - 3] + '...'\n",
           "beyond_n_dots": "def truncate(text, n):\n    return text if len(text) <= n else text[:n] + '...'\n",
           "within_n_unicode": "def truncate(text, n):\n    return text if len(text) <= n else text[:n - 1] + '\\u2026'\n",
           "beyond_n_unicode": "def truncate(text, n):\n    return text if len(text) <= n else text[:n] + '\\u2026'\n"})}
for name, (path, impls) in AMB.items():
    t = NEW_TASKS[name]
    base = exp.oracle(t, "")["oracle_pass"]
    print(f"{name:18} shared oracle fails on original={not base}")
    ok &= not base
    for reading, impl in impls.items():
        d = diff_for(t, {path: impl})
        shared = exp.oracle(t, d)["oracle_pass"]
        hits = [r for r, src in t["readings"].items() if check(t, src)(d)]
        good = shared and hits == [reading]
        ok &= good
        print(f"   {reading:18} passes shared={shared} classified as {hits}")
print("ALL OK" if ok else "FIX")
