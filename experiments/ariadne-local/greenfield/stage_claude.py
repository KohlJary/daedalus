"""Stage the greenfield Claude runs (see RUNBOOK.md). Safe to re-run. Nothing staged contains the oracles."""
import shutil, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "gate_exp"))
import greenfield as g
for name, feat in g.FEATURES.items():
    for kind in ("solo", "plan"):
        d = HERE / "claude" / kind / name
        (d / "project").mkdir(parents=True, exist_ok=True)
        (d / "spec.md").write_text(feat["description"])
        if kind == "solo":
            (d / "project" / "README.md").write_text(feat["description"])
    for art in sorted((HERE / "results" / "artifacts" / name / "gf_llmplan").glob("rep*")):
        d = HERE / "claude" / "polish" / name / art.name
        if not (d / "project").exists():
            shutil.copytree(art, d / "project")
        (d / "spec.md").write_text(feat["description"])
        print(f"polish staged: {name}/{art.name}")
leak = subprocess.run(["grep", "-rl", "test_zz_oracle\\|UNITS_ORACLE\\|KVSTORE_ORACLE", str(HERE / "claude")], capture_output=True, text=True).stdout
print("oracle leak check:", leak or "clean")
