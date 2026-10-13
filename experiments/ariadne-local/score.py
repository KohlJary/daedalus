"""Score spike RESULT lines against what each task actually asked for."""
import sys, collections
def ok(r):
    if r.get("pass") == "ERROR": return False
    n = int(r.get("tests_passed", 0)); T = r.get("tests_touched") == "True"; C = r.get("calc_touched") == "True"
    return {"add_sub":    n == 3 and T and C,                         # sub + test_sub added, add/mul kept
            "fix_bug":    n == 2 and C and not T,                     # fixed code, tests untouched
            "new_module": n >= 4 and r.get("check") == "ok" and not C, # mean works, raises, calc untouched
            }[r["task"]]
rows = collections.defaultdict(lambda: collections.defaultdict(list)); secs = collections.defaultdict(list)
for f in sys.argv[1:]:
    for line in open(f):
        r = dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv)
        rows[r["model"]][r["task"]].append(ok(r)); secs[r["model"]].append(int(r.get("secs", 0) or 0))
print(f"{'model':28} {'add_sub':8} {'fix_bug':8} {'new_mod':8} {'total':6} {'avg s':5}")
for m, t in rows.items():
    cells = [f"{sum(t[k])}/{len(t[k])}" for k in ("add_sub", "fix_bug", "new_module")]
    tot = sum(sum(v) for v in t.values()); n = sum(len(v) for v in t.values())
    print(f"{m:28} {cells[0]:8} {cells[1]:8} {cells[2]:8} {tot}/{n:<4} {sum(secs[m])//max(len(secs[m]),1):5}")
