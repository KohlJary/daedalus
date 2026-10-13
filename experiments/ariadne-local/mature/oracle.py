"""Run a mature task's hidden oracle on a project tree: the ORIGINAL test suite (from base/) plus the oracle
module, against the tree's source. The tree's own test edits are ignored."""
import shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "base"
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA"]


def run_oracle(tree: Path, oracle_src: str, timeout=300) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="mature-oracle-"))
    try:
        shutil.copytree(tree, tmp / "p", ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        shutil.rmtree(tmp / "p" / "tests", ignore_errors=True)
        shutil.copytree(BASE / "tests", tmp / "p" / "tests")
        (tmp / "p" / "tests" / "test_zz_oracle.py").write_text(oracle_src)
        env = {"PYTHONPATH": str(tmp / "p" / "src"), "PATH": "/usr/bin:/bin", "HOME": str(tmp)}
        r = subprocess.run(PYTEST, cwd=tmp / "p", capture_output=True, text=True, timeout=timeout, env=env)
        lines = r.stdout.splitlines()
        oracle_tests = {l.split("::")[-1].split()[0]: l.split()[0] for l in lines
                        if l.startswith(("PASSED", "FAILED", "ERROR")) and "test_zz_oracle.py::" in l}
        regressions = [l for l in lines if l.startswith(("FAILED", "ERROR")) and "test_zz_oracle.py" not in l]
        return dict(oracle_pass=r.returncode == 0, oracle_tests=oracle_tests, regressions=regressions,
                    summary=lines[-1] if lines else r.stderr[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
