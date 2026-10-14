"""Rebuild ariadne_src/: the Ariadne code the experiments run, pinned to mature/BASE_COMMIT plus one backport
from PR #24 (atomic commits stage exactly the diff; see ariadne_src/BACKPORT after running)."""
import io, shutil, subprocess, tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
commit = (HERE.parent / "mature" / "BASE_COMMIT").read_text().strip()
repo = HERE.parents[2]
out = HERE / "ariadne_src"
shutil.rmtree(out, ignore_errors=True)
tar = subprocess.run(["git", "-C", str(repo), "archive", commit, "src"], capture_output=True, check=True).stdout
tmp = HERE / "_src_tmp"
shutil.rmtree(tmp, ignore_errors=True)
tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp)
(tmp / "src").rename(out)
shutil.rmtree(tmp)
orch = out / "daedalus" / "ariadne" / "orchestrator.py"
s = orch.read_text()
for a, b in [('                ["git", "apply", str(diff_file)],', '                ["git", "apply", "--index", str(diff_file)],  # experiment backport of PR #24: stage exactly the diff'),
             ('        return ["git", "commit", "-a", "-m", signed_message]', '        return ["git", "commit", "-m", signed_message]  # experiment backport of PR #24: no -a'),
             ('    return ["git", "commit", "-a", f"--author=Daedalus <{email}>", "-m", message]', '    return ["git", "commit", f"--author=Daedalus <{email}>", "-m", message]  # experiment backport of PR #24: no -a')]:
    assert s.count(a) == 1, a
    s = s.replace(a, b)
orch.write_text(s)
(out / "BACKPORT").write_text((HERE / "BACKPORT.md").read_text())
print(f"ariadne_src rebuilt at {commit[:7]} + PR #24 commit fix")
