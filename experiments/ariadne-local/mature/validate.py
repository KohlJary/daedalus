import shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from mature_tasks import TASKS
from refs import REFS
from oracle import run_oracle, BASE
ok = True
for name, task in TASKS.items():
    base = run_oracle(BASE, task["oracle"])
    tree = Path(tempfile.mkdtemp()) / "p"
    shutil.copytree(BASE, tree)
    for rel, old, new in REFS[name]:
        f = tree / rel; s = f.read_text()
        assert s.count(old) == 1, (name, rel, old[:60], s.count(old))
        f.write_text(s.replace(old, new))
    ref = run_oracle(tree, task["oracle"])
    good = (not base["oracle_pass"]) and ref["oracle_pass"]
    ok &= good
    failing_on_base = sum(v != "PASSED" for v in base["oracle_tests"].values())
    print(f"{name:14} base: {failing_on_base}/{len(base['oracle_tests'])} oracle tests fail, regressions={len(base['regressions'])} | "
          f"ref: pass={ref['oracle_pass']} {ref['summary']}")
    if not good:
        print("   ref failing:", {k: v for k, v in ref["oracle_tests"].items() if v != "PASSED"}, ref["regressions"][:5])
    shutil.rmtree(tree.parent)
print("ALL OK" if ok else "FIX")
