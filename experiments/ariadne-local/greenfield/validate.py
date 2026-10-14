import shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).parent.parent / "gate_exp"))
import exp, feature, specs, refs
ok = True
for name, spec, oracle, ref, bugs in [("units", specs.UNITS_SPEC, specs.UNITS_ORACLE, refs.UNITS, refs.UNITS_BUGS),
                                      ("kvstore", specs.KVSTORE_SPEC, specs.KVSTORE_ORACLE, refs.KVSTORE, refs.KVSTORE_BUGS)]:
    empty = exp.make_repo({"README.md": spec})
    base = feature.run_oracle(empty, oracle)["oracle_pass"]
    for rel, content in ref.items():
        (empty / rel).parent.mkdir(parents=True, exist_ok=True); (empty / rel).write_text(content)
    r = feature.run_oracle(empty, oracle)
    caught = []
    for rel, a, b in bugs:
        s = (empty / rel).read_text(); assert s.count(a) == 1, (name, a)
        (empty / rel).write_text(s.replace(a, b)); caught.append(not feature.run_oracle(empty, oracle)["oracle_pass"]); (empty / rel).write_text(s)
    good = (not base) and r["oracle_pass"] and all(caught)
    ok &= good
    print(f"{name:8} empty project fails={not base}  reference passes={r['oracle_pass']} ({r['oracle_out']})  planted bugs caught={caught}")
    if not r["oracle_pass"]:
        print("   failing:", {k: v for k, v in r["oracle_tests"].items() if v != "PASSED"})
    shutil.rmtree(empty.parent)
print("ALL OK" if ok else "FIX")
