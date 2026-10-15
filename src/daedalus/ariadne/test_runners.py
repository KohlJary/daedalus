"""
Test selection and test runners for Ariadne's verifier, for every language the palace analyzes.

Selection (`select_tests`) asks the palace which tests reach the definitions a diff touches, in the
patched workspace, and adds the language's conventional test files and any changed test files. The
verifier unions that with its older name-based match, so a test either way gets run.

Runners (`plan_runs`, `run_tests`) group the selected test files by language and run each group with
that ecosystem's tool from the directory that owns it (the nearest go.mod, Cargo.toml, package.json,
pom.xml or build.gradle). Python uses the verifier's `test_cmd` (pytest by default). Every runner can be
replaced per language with `test_cmds={"Go": [...]}`; the selected files are appended to the command.

A run that executes no test (every selected file missing, only skipped tests, a filter matching
nothing, or output the runner's parser can't read) sets `ran_nothing`, which the verifier treats as
"no tests matched", not as a pass, even when another language's run passed: the change that run was
selected for is unverified. Maven and Gradle are counted from their JUnit XML reports.
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
    ran_nothing: bool = False  # some run executed no test (see run_tests)


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


def _csharp_test_classes(repo: Path, rel_file: str) -> List[str]:
    """The test classes a C# test file defines (by the palace's analyzer), else its file name."""
    from ..labyrinth.languages import get_language_registry
    support = get_language_registry().get_by_extension(Path(rel_file))
    try:
        elements = support.analyze_file(repo / rel_file, repo) if support is not None else []
    except Exception:
        elements = []
    # Classes holding a test attribute ([Fact], [Theory], [Test], [TestCase], [TestMethod], [UnityTest]);
    # helper classes in the same file (a capturing logger, a null scope) are left out of the filter
    try:
        lines = (repo / rel_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    marked = [i + 1 for i, line in enumerate(lines)
              if re.search(r"\[\s*(Fact|Theory|Test|TestCase|TestCaseSource|TestMethod|DataTestMethod|UnityTest)\b", line)]
    classes = [e for e in elements if e.element_type == "class"]
    with_tests = set()
    for line in marked:
        holders = [c for c in classes if c.line <= line <= (c.end_line or c.line)]
        if holders:
            with_tests.add(min(holders, key=lambda c: (c.end_line or c.line) - c.line).simple_name)
    names = sorted(with_tests) or sorted({c.simple_name for c in classes})
    return names or [Path(rel_file).stem]


def _nearest_csproj(repo: Path, rel_file: str) -> Optional[str]:
    """The repo-relative path of the .csproj owning a file (the nearest one above it)."""
    parts = Path(rel_file).parent.parts
    for i in range(len(parts), -1, -1):
        d = repo / Path(*parts[:i]) if i else repo
        found = sorted(d.glob("*.csproj"))
        if found:
            return found[0].relative_to(repo).as_posix()
    return None


def is_unity_project(repo: Path, rel_file: str) -> bool:
    """Unity keeps ProjectSettings/ProjectVersion.txt at its root; its .csproj files are generated."""
    parts = Path(rel_file).parent.parts
    return any((repo / Path(*parts[:i]) / "ProjectSettings" / "ProjectVersion.txt").exists()
               for i in range(len(parts), -1, -1))


BUILD_SOURCES = (".cs", ".csproj", ".razor", ".cshtml", ".props", ".targets")


def dotnet_build(repo: Path, changed: List[str], timeout: int = 600) -> Tuple[bool, List[str], List[str]]:
    """Build each .NET project a diff touches: C# type errors only show at build time. A changed
    Directory.Build.props/.targets builds every project under it. Unity projects (they build in the Unity
    editor) and files no project owns are reported as skipped. Returns (passed, errors, skipped)."""
    projects: List[str] = []
    skipped: List[str] = []

    def add(project: str) -> None:
        if is_unity_project(repo, project):
            if f"build: {project} (a Unity project; it builds in the Unity editor)" not in skipped:
                skipped.append(f"build: {project} (a Unity project; it builds in the Unity editor)")
        elif project not in projects:
            projects.append(project)

    for f in changed:
        if not f.endswith(BUILD_SOURCES) or not (repo / f).exists():
            continue
        if f.endswith((".props", ".targets")):
            base = repo / Path(f).parent
            found = sorted(p.relative_to(repo).as_posix() for p in base.rglob("*.csproj")
                           if not ({"bin", "obj", "node_modules"} & set(p.relative_to(repo).parts)))
            for project in found:
                add(project)
            if not found:
                skipped.append(f"build: {f} (no project under it)")
            continue
        project = f if f.endswith(".csproj") else _nearest_csproj(repo, f)
        if project:
            add(project)
        else:
            skipped.append(f"build: {f} (no .csproj owns it)")
    errors: List[str] = []
    for project in projects:
        try:
            r = subprocess.run(["dotnet", "build", project, "--nologo", "-v", "q", "-clp:NoSummary"],
                               cwd=repo, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return False, [f"{project}: dotnet not found; install the .NET SDK or turn off ariadne.build_gate"], skipped
        except subprocess.TimeoutExpired:
            return False, [f"{project}: dotnet build timed out"], skipped
        if r.returncode != 0:
            lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if re.search(r"\berror\b", ln)]
            errors.extend(dict.fromkeys(lines[:30]) or [f"{project}: dotnet build exited {r.returncode}"])
    return not errors, errors, skipped


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
            # One run per package, so a package whose tests all skip is caught on its own
            packages: Dict[Tuple[str, str], List[str]] = {}
            for f in files:
                root = _nearest(repo, f, ("go.mod",)) or "."
                pkg = Path(_rel_to(f, root)).parent.as_posix()
                packages.setdefault((root, "./" if pkg == "." else f"./{pkg}"), []).append(f)
            for (root, pkg), fs in sorted(packages.items()):
                runs.append(RunPlan(lang, root, ["go", "test", "-v", pkg], fs))
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
            # Each test project that owns a selected file, filtered to the selected classes (a test class
            # is conventionally named for its file). Unity projects have no dotnet test.
            projects: Dict[str, List[str]] = {}
            for f in files:
                projects.setdefault(_nearest_csproj(repo, f) or "", []).append(f)
            for project, fs in sorted(projects.items()):
                if not project or is_unity_project(repo, fs[0]):
                    problems.append(f"C#: no dotnet test project for {', '.join(fs)}"
                                    + (" (a Unity project: run its tests in the Unity editor, or set test_cmds)"
                                       if project else ""))
                    continue
                classes = sorted({c for f in fs for c in _csharp_test_classes(repo, f)})
                filter_ = "|".join(f"FullyQualifiedName~{c}" for c in classes)
                runs.append(RunPlan(lang, ".", ["dotnet", "test", project, "--nologo", "--filter", filter_], fs))
        else:
            problems.append(f"No test runner known for {lang} ({len(files)} test file(s)); "
                            f"pass test_cmds={{'{lang}': [...]}} to run them")
    # Python and override commands take the files as arguments
    for run in runs:
        if run.language == PYTHON or run.language in overrides:
            run.command = [*run.command, *(_rel_to(f, run.cwd) for f in run.files)]
    return runs, problems


def _junit_reports(directory: Path, since: float) -> Tuple[int, int]:
    """(ran, failed) summed over JUnit XML reports written since `since` (Maven's target/surefire-reports,
    Gradle's build/test-results): their console output doesn't reliably count tests."""
    import xml.etree.ElementTree as ET
    ran = failed = 0
    for pattern in ("**/target/surefire-reports/TEST-*.xml", "**/build/test-results/**/TEST-*.xml"):
        for report in directory.glob(pattern):
            try:
                if report.stat().st_mtime < since:
                    continue
                root = ET.parse(report).getroot()
            except (OSError, ET.ParseError):
                continue
            suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
            for suite in suites:
                tests, skipped = int(suite.get("tests", 0)), int(suite.get("skipped", 0))
                bad = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
                ran += tests - skipped
                failed += bad
    return ran, failed


def _count(language: str, out: str, returncode: int) -> Tuple[Optional[int], int]:
    """(tests executed, failed) from a runner's output; executed is None when the output can't be read.
    Skipped tests don't count as executed."""
    def num(pattern: str, flags=0) -> int:
        return sum(int(m) for m in re.findall(pattern, out, flags))

    if language == PYTHON:
        if not re.search(r"\d+ (passed|failed|skipped|error|xfailed|xpassed|deselected)|no tests ran", out):
            return None, 0
        failed = num(r"(\d+) failed") + num(r"(\d+) errors?\b")
        return num(r"(\d+) passed") + num(r"(\d+) xpassed") + failed, failed
    if language == "Go":
        passed, failed = len(re.findall(r"^\s*--- PASS", out, re.M)), len(re.findall(r"^\s*--- FAIL", out, re.M))
        return passed + failed, failed
    if language == "Rust":
        if "test result:" not in out:
            return None, 0
        passed, failed = num(r"test result: \w+\. (\d+) passed"), num(r"(\d+) failed;")
        return passed + failed, failed
    if language == "JavaScript":
        jest = re.findall(r"^\s*Tests:?\s+(.*)$", out, re.M)  # jest "Tests: 1 failed, 2 passed", vitest "Tests  3 passed (3)"
        node = re.findall(r"^\s*[#ℹ]\s*(pass|fail)\s+(\d+)", out, re.M)  # node --test (TAP "#", spec "ℹ")
        if jest:
            line = jest[-1]
            passed = sum(int(m) for m in re.findall(r"(\d+) passed", line))
            failed = sum(int(m) for m in re.findall(r"(\d+) failed", line))
            return passed + failed, failed
        if node:
            passed = sum(int(n) for k, n in node if k == "pass")
            failed = sum(int(n) for k, n in node if k == "fail")
            return passed + failed, failed
        mocha = re.search(r"(\d+) passing", out)
        if mocha:  # mocha: "3 passing", "1 failing", "2 pending"
            failed = num(r"(\d+) failing")
            return int(mocha.group(1)) + failed, failed
        ava = re.search(r"(\d+) tests? passed", out)
        if ava:
            failed = num(r"(\d+) tests? failed")
            return int(ava.group(1)) + failed, failed
        if re.search(r"No tests found|No test files found", out):
            return 0, 0
        return None, 0
    if language == "Ruby":
        rspec = re.search(r"(\d+) examples?, (\d+) failures?(?:, (\d+) pending)?", out)
        if rspec:
            examples, failures, pending = (int(g or 0) for g in rspec.groups())
            return examples - pending, failures
        mini = re.search(r"(\d+) runs?, \d+ assertions?, (\d+) failures?, (\d+) errors?, (\d+) skips?", out)
        if mini:
            runs, failures, errors, skips = (int(g) for g in mini.groups())
            return runs - skips, failures + errors
        return None, 0
    if language == "C#":
        if not re.search(r"(Passed|Failed)!\s+-|Total tests:|No test (matches|is available)", out):
            return None, 0
        failed = num(r"Failed:\s+(\d+)")
        return num(r"Passed:\s+(\d+)") + failed, failed
    return None, 0


def run_tests(repo: Path, runs: List[RunPlan], timeout: int = 300) -> RunOutcome:
    """Run every planned run. A run that executed no test (every selected file gone, only skipped tests,
    nothing matched, or output that can't be read) leaves the change it was selected for unverified, so
    `ran_nothing` is set whenever any run did that, not only when all did."""
    import time
    outcome = RunOutcome(passed=True)
    for run in runs:
        existing = [f for f in run.files if (repo / f).exists()]
        if not existing:
            outcome.errors.append(f"{run.language}: none of the selected test files exist: {', '.join(run.files)}")
            outcome.ran_nothing = True
            continue
        started = time.time()
        try:
            r = subprocess.run(run.command, cwd=repo / run.cwd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            outcome.passed = False
            outcome.errors.append(f"{run.language}: tests timed out ({' '.join(run.command[:3])} ...)")
            continue
        except FileNotFoundError:
            outcome.passed = False
            outcome.errors.append(f"{run.language}: test runner not found: {run.command[0]}")
            continue
        out = r.stdout + "\n" + r.stderr
        if run.language in ("Java", "Kotlin"):
            ran, failed = _junit_reports(repo / run.cwd, started - 1)
            ran = ran if (ran or r.returncode == 0) else None
        else:
            ran, failed = _count(run.language, out, r.returncode)
        outcome.ran += ran or 0
        outcome.failed += failed
        if r.returncode != 0:
            outcome.passed = False
            lines = [ln for ln in out.splitlines() if re.search(r"FAIL|ERROR|Error|panic|failed", ln)]
            outcome.errors.extend(f"{run.language}: {ln.strip()}" for ln in lines[:20])
            if not lines:
                outcome.errors.append(f"{run.language}: exited {r.returncode}")
        elif not ran:
            outcome.ran_nothing = True
            outcome.errors.append(f"{run.language}: {'no test executed' if ran == 0 else 'could not tell whether any test ran'}"
                                  f" ({' '.join(run.command[:4])} ...)")
    if not runs:
        outcome.ran_nothing = True
    return outcome
