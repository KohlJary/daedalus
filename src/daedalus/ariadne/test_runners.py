"""
Test selection and test runners for Ariadne's verifier, for every language the palace analyzes.

Selection (`select_tests`) asks the palace which tests reach the definitions a diff touches, in the
patched workspace, and adds the language's conventional test files and any changed test files. The
verifier unions that with its older name-based match, so a test either way gets run.

Runners (`plan_runs`, `run_tests`) group the selected test files by language and run each group with
that ecosystem's tool from the directory that owns it (the nearest go.mod, Cargo.toml, package.json,
pom.xml or build.gradle). Python uses the verifier's `test_cmd` (pytest by default). Every runner can be
replaced per language with `test_cmds={"Go": [...]}`; the selected files are appended to the command.

A run that executes nothing (`go test` on a package with "[no test files]", `cargo test` running 0
tests, every selected file missing) reports `ran_nothing`, which the verifier treats as "no tests
matched", not as a pass.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PYTHON = "Python"


@dataclass
class TestSelection:
    """Which test files to run and why."""
    __test__ = False  # not a pytest test class
    files: List[str] = field(default_factory=list)
    palace: List[str] = field(default_factory=list)       # files of tests whose call chains reach the change
    convention: List[str] = field(default_factory=list)   # foo_test.go, foo.test.ts, tests/test_foo.py, ...
    changed_nodes: List[str] = field(default_factory=list)
    error: Optional[str] = None                           # the palace couldn't build a graph


@dataclass
class RunPlan:
    language: str
    cwd: str                  # repo-relative directory the command runs in
    command: List[str]
    files: List[str]          # repo-relative test files this run covers


@dataclass
class RunOutcome:
    passed: bool
    ran: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    ran_nothing: bool = False


def select_tests(repo: Path, diff_text: str, changed_files: List[str], max_depth: int = 6) -> TestSelection:
    """Tests for a diff applied in `repo`, from the palace's call graph of the patched code."""
    from ..labyrinth.query import (build_query_graph, changed_lines_from_diff, convention_tests, in_test_file,
                                   nodes_for_lines, tests_reaching)

    selection = TestSelection()
    try:
        graph = build_query_graph(repo).graph
    except Exception as e:  # selection must not crash verification; the name-based match still runs
        selection.error = f"palace graph failed: {e}"
        return selection
    touched = nodes_for_lines(graph, changed_lines_from_diff(diff_text))
    nodes = sorted({n for ids in touched.values() for n in ids})
    selection.changed_nodes = nodes
    hits = tests_reaching(graph, nodes, max_depth) if nodes else []
    selection.palace = sorted({graph.nodes[t].file for t in hits})
    sources = [f for f in changed_files if not in_test_file(f)]
    selection.convention = convention_tests(repo, sources)
    selection.files = sorted(set(selection.palace) | set(selection.convention))
    return selection


def _language_name(file: str) -> Optional[str]:
    from ..labyrinth.query import _language
    language = _language(file)
    return language.name if language is not None else (PYTHON if file.endswith(".py") else None)


def _nearest(repo: Path, rel_file: str, markers: Tuple[str, ...]) -> Optional[str]:
    """The repo-relative directory of the nearest ancestor holding one of `markers`."""
    parts = Path(rel_file).parent.parts
    for i in range(len(parts), -1, -1):
        d = Path(*parts[:i]) if i else Path(".")
        if any((repo / d / m).exists() for m in markers):
            return d.as_posix()
    return None


def _rel_to(path: str, base: str) -> str:
    return path if base in ("", ".") else Path(path).relative_to(base).as_posix()


def _js_runner(repo: Path, root: str) -> List[str]:
    """vitest or jest when the package depends on it, else the package's own test script."""
    try:
        pkg = json.loads((repo / root / "package.json").read_text())
    except (OSError, ValueError):
        pkg = {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    if "vitest" in deps:
        return ["npx", "--no-install", "vitest", "run"]
    if "jest" in deps or "ts-jest" in deps:
        return ["npx", "--no-install", "jest"]
    return ["npm", "test", "--"]


def plan_runs(repo: Path, test_files: List[str], python_cmd: List[str],
              overrides: Optional[Dict[str, List[str]]] = None) -> Tuple[List[RunPlan], List[str]]:
    """Group test files into runs. Returns (runs, problems): a problem is a language with no runner."""
    overrides = overrides or {}
    by_language: Dict[str, List[str]] = {}
    for f in test_files:
        lang = _language_name(f)
        if lang:
            by_language.setdefault(lang, []).append(f)
    runs: List[RunPlan] = []
    problems: List[str] = []
    for lang, files in sorted(by_language.items()):
        if lang in overrides:
            runs.append(RunPlan(lang, ".", list(overrides[lang]), files))
        elif lang == PYTHON:
            runs.append(RunPlan(lang, ".", list(python_cmd), files))
        elif lang == "Go":
            packages: Dict[str, Set[str]] = {}
            for f in files:
                root = _nearest(repo, f, ("go.mod",)) or "."
                pkg = Path(_rel_to(f, root)).parent.as_posix()
                packages.setdefault(root, set()).add("./" if pkg == "." else f"./{pkg}")
            for root, pkgs in sorted(packages.items()):
                runs.append(RunPlan(lang, root, ["go", "test", "-v", *sorted(pkgs)],
                                    [f for f in files if (_nearest(repo, f, ("go.mod",)) or ".") == root]))
        elif lang == "Rust":
            groups: Dict[str, List[str]] = {}
            for f in files:
                root = _nearest(repo, f, ("Cargo.toml",)) or "."
                groups.setdefault(root, []).append(f)
            for root, fs in sorted(groups.items()):
                integration = sorted({Path(f).stem for f in fs if _rel_to(f, root).startswith("tests/")})
                args = [a for stem in integration for a in ("--test", stem)]
                if any(not _rel_to(f, root).startswith("tests/") for f in fs):
                    args = ["--lib", "--bins", *args]  # unit tests live in the crate's own sources
                runs.append(RunPlan(lang, root, ["cargo", "test", *args], fs))
        elif lang in ("JavaScript", "TypeScript", "TSX"):
            groups = {}
            for f in files:
                root = _nearest(repo, f, ("package.json",)) or "."
                groups.setdefault(root, []).append(f)
            for root, fs in sorted(groups.items()):
                runs.append(RunPlan("JavaScript", root, [*_js_runner(repo, root), *(_rel_to(f, root) for f in fs)], fs))
        elif lang in ("Java", "Kotlin"):
            groups = {}
            for f in files:
                root = _nearest(repo, f, ("pom.xml", "build.gradle", "build.gradle.kts")) or "."
                groups.setdefault(root, []).append(f)
            for root, fs in sorted(groups.items()):
                classes = sorted({Path(f).stem for f in fs})
                if (repo / root / "pom.xml").exists():
                    cmd = ["mvn", "-q", "test", f"-Dtest={','.join(classes)}", "-Dsurefire.failIfNoSpecifiedTests=false"]
                else:
                    gradle = "./gradlew" if (repo / root / "gradlew").exists() else "gradle"
                    cmd = [gradle, "test", *(a for c in classes for a in ("--tests", c))]
                runs.append(RunPlan(lang, root, cmd, fs))
        elif lang == "Ruby":
            specs = [f for f in files if "spec" in Path(f).parts or f.endswith("_spec.rb")]
            minis = [f for f in files if f not in specs]
            if specs:
                runs.append(RunPlan(lang, ".", ["bundle", "exec", "rspec", *specs], specs))
            for f in minis:
                runs.append(RunPlan(lang, ".", ["bundle", "exec", "ruby", "-Itest", f], [f]))
        elif lang == "C#":
            runs.append(RunPlan(lang, ".", ["dotnet", "test"], files))
        else:
            problems.append(f"No test runner known for {lang} ({len(files)} test file(s)); "
                            f"pass test_cmds={{'{lang}': [...]}} to run them")
    # Python and override commands take the files as arguments
    for run in runs:
        if run.language == PYTHON or run.language in overrides:
            run.command = [*run.command, *(_rel_to(f, run.cwd) for f in run.files)]
    return runs, problems


def _count(language: str, out: str, returncode: int) -> Tuple[int, int, bool]:
    """(ran, failed, ran_nothing) from a runner's output, best effort."""
    def num(pattern: str) -> int:
        return sum(int(m) for m in re.findall(pattern, out))

    if language == PYTHON:
        passed, failed = num(r"(\d+) passed"), num(r"(\d+) failed")
        return passed + failed, failed, returncode == 5  # pytest: 5 = no tests collected
    if language == "Go":
        passed, failed = len(re.findall(r"^\s*--- PASS", out, re.M)), len(re.findall(r"^\s*--- FAIL", out, re.M))
        nothing = passed + failed == 0 and returncode == 0 and ("[no test files]" in out or "no tests to run" in out)
        return passed + failed, failed, nothing
    if language == "Rust":
        passed, failed = num(r"test result: \w+\. (\d+) passed"), num(r"(\d+) failed;")
        return passed + failed, failed, returncode == 0 and passed + failed == 0 and "test result" in out
    if language == "JavaScript":
        passed, failed = num(r"(\d+) passed"), num(r"(\d+) failed")
        nothing = bool(re.search(r"No tests found|No test files found", out))
        return passed + failed, failed, nothing
    if language in ("Java", "Kotlin"):
        ran, failures = num(r"Tests run: (\d+),"), num(r"Failures: (\d+)") + num(r"Errors: (\d+)")
        return ran, failures, False
    if language == "Ruby":
        ran, failed = num(r"(\d+) examples?"), num(r"(\d+) failures?")
        return ran, failed, returncode == 0 and "0 examples" in out
    if language == "C#":
        passed, failed = num(r"Passed:\s+(\d+)"), num(r"Failed:\s+(\d+)")
        return passed + failed, failed, False
    return 0, 0, False


def run_tests(repo: Path, runs: List[RunPlan], timeout: int = 300) -> RunOutcome:
    """Run every planned run; passes only if each one did and at least one test file still exists."""
    outcome = RunOutcome(passed=True)
    any_ran = False
    for run in runs:
        existing = [f for f in run.files if (repo / f).exists()]
        if not existing:
            outcome.errors.append(f"{run.language}: none of the selected test files exist: {', '.join(run.files)}")
            continue
        try:
            r = subprocess.run(run.command, cwd=repo / run.cwd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            outcome.passed = False
            outcome.errors.append(f"{run.language}: tests timed out ({' '.join(run.command[:3])} ...)")
            any_ran = True
            continue
        except FileNotFoundError:
            outcome.passed = False
            outcome.errors.append(f"{run.language}: test runner not found: {run.command[0]}")
            continue
        out = r.stdout + "\n" + r.stderr
        ran, failed, nothing = _count(run.language, out, r.returncode)
        outcome.ran += ran
        outcome.failed += failed
        if nothing:
            outcome.errors.append(f"{run.language}: the runner ran no tests ({' '.join(run.command[:4])} ...)")
            continue
        any_ran = True
        if r.returncode != 0:
            outcome.passed = False
            lines = [ln for ln in out.splitlines() if re.search(r"FAIL|ERROR|Error|panic|failed", ln)]
            outcome.errors.extend(f"{run.language}: {ln.strip()}" for ln in lines[:20])
            if not lines:
                outcome.errors.append(f"{run.language}: exited {r.returncode}")
    outcome.ran_nothing = not any_ran
    return outcome
