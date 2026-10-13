"""Stage the Claude runs (run on/after 2026-10-23, see RUNBOOK.md). Safe to re-run.
  solo/<task>/      clean copy of the repo + feature.md, for a Claude-solo subagent
  review/<task>/    feature.md + plan.json (the local planner's cached plan) + project/, for a plan reviewer
Neither contains the oracles."""
import json, shutil, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "gate_exp"))
import mature_exp as m
for name, feat in m.FEATURES.items():
    solo = HERE / "claude" / "solo" / name
    if not (solo / "project").exists():
        solo.mkdir(parents=True, exist_ok=True)
        repo = m.make_mature_repo()
        shutil.copytree(repo, solo / "project")
        shutil.rmtree(repo.parent)
    (solo / "feature.md").write_text(f"# {feat['title']}\n\n{feat['description']}\n")
    plan = HERE / "results" / "plans" / f"{name}.json"
    rev = HERE / "claude" / "review" / name
    if plan.exists():
        rev.mkdir(parents=True, exist_ok=True)
        if not (rev / "project").exists():
            shutil.copytree(solo / "project", rev / "project", ignore=shutil.ignore_patterns(".git"))
        (rev / "feature.md").write_text((solo / "feature.md").read_text())
        (rev / "plan.json").write_text(json.dumps({"packages": json.loads(plan.read_text())["raw"]}, indent=2))
        print(f"{name}: solo + review staged")
    else:
        print(f"{name}: solo staged; review waits for the local planner's plan (mature run, llmplan condition)")
leak = subprocess.run(["grep", "-rl", "test_zz_oracle\\|ORACLE", str(HERE / "claude")], capture_output=True, text=True).stdout
print("oracle leak check:", leak or "clean")
