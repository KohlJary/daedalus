"""
Diff Verification

Ariadne's mechanical gate. Each worker diff is applied to a fresh copy of the whole repository
(not a slice of it) and checked there. What is narrowed is which tests run: those whose call chains
reach the definitions the diff touches, by the palace's call graph of the patched code (the same
graph as `daedalus palace tests-for`), plus each language's conventional test files, the tests the
older name match finds, and any changed test files.

Flow:
1. Copy the repository to a temp workspace and apply the diff
2. Syntax-check every changed file: Python by compiling it, other languages by parsing them with
   tree-sitter (a gate that runs even when no test does)
3. Type check and lint the changed Python modules
4. Run the selected tests with each language's runner (test_runners.py: pytest, go test, cargo,
   jest/vitest, Maven/Gradle, rspec, dotnet; override per language with `test_cmds`)
5. If no test was selected, or the runners ran none (the files vanished, `[no test files]`), the diff
   is not verified (`no_tests_matched`): it fails closed, and the orchestrator routes it to human
   review instead of merging it (gameplan T-e4, issue #15). `tests_run` tells the two apart from a
   pass.
"""

import re
import subprocess
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime, timezone

from .diff_bus import Diff, CausalChain, DiffStatus
from .test_runners import BUILD_SOURCES, dotnet_build, plan_runs, run_tests, select_tests


@dataclass
class VerificationResult:
    """Result of verifying one diff."""
    diff_id: str
    passed: bool
    duration_seconds: float

    # Individual check results
    typecheck_passed: bool = True
    typecheck_errors: List[str] = field(default_factory=list)

    lint_passed: bool = True
    lint_errors: List[str] = field(default_factory=list)

    compile_passed: bool = True
    compile_errors: List[str] = field(default_factory=list)

    tests_passed: bool = True
    # True when no test matched the diff: the tests did not pass, they never ran (T-e4)
    no_tests_matched: bool = False
    tests_run: int = 0
    tests_failed: int = 0
    test_errors: List[str] = field(default_factory=list)

    # What was verified
    modules_checked: List[str] = field(default_factory=list)
    tests_executed: List[str] = field(default_factory=list)
    # Why each test file was selected: palace (call graph), convention, name (the older match), changed
    tests_selected_by: Dict[str, List[str]] = field(default_factory=dict)
    test_commands: List[str] = field(default_factory=list)
    # Checks that couldn't run here (no tree-sitter for a language's syntax gate, the palace graph failing)
    skipped_checks: List[str] = field(default_factory=list)

    # Timestamps
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            "diff_id": self.diff_id,
            "passed": self.passed,
            "duration_seconds": self.duration_seconds,
            "typecheck": {
                "passed": self.typecheck_passed,
                "errors": self.typecheck_errors,
            },
            "lint": {
                "passed": self.lint_passed,
                "errors": self.lint_errors,
            },
            "compile": {
                "passed": self.compile_passed,
                "errors": self.compile_errors,
            },
            "tests": {
                "passed": self.tests_passed,
                "no_tests_matched": self.no_tests_matched,
                "run": self.tests_run,
                "failed": self.tests_failed,
                "errors": self.test_errors,
                "commands": self.test_commands,
            },
            "scope": {
                "modules": self.modules_checked,
                "tests": self.tests_executed,
                "selected_by": self.tests_selected_by,
            },
            "skipped_checks": self.skipped_checks,
            "timing": {
                "started": self.started_at,
                "completed": self.completed_at,
            },
        }


class CausalSliceVerifier:
    """
    Verifies a diff in a full copy of the repository, running the checks chosen for it.

    1. Apply the diff to a temporary copy of the whole repository
    2. Identify affected modules from the causal chain (or the diff's file names)
    3. Compile the changed Python files
    4. Type check those modules and lint those files
    5. Run the tests matched to them by name, plus changed test files; none matched fails closed
    """

    def __init__(
        self,
        repo_path: Path,
        python_path: str = "python",
        typecheck_cmd: Optional[List[str]] = None,
        lint_cmd: Optional[List[str]] = None,
        test_cmd: Optional[List[str]] = None,
        require_tests: bool = True,
        test_cmds: Optional[Dict[str, List[str]]] = None,
        build_gate: bool = True,
    ):
        """
        Initialize verifier.

        Args:
            repo_path: Path to the git repository
            python_path: Python interpreter to use
            typecheck_cmd: Command for type checking (default: mypy)
            lint_cmd: Command for linting (default: ruff)
            test_cmd: Command for running Python tests (default: pytest)
            require_tests: A diff no test matched is not verified (default). False lets it pass
                on the other checks alone; for harnesses that stub the test command out.
            test_cmds: Per-language test commands, keyed by language name ("Go", "TypeScript", ...),
                replacing the built-in runner; the selected test files are appended.
            build_gate: Build the .NET projects a diff touches (`dotnet build`) as their type check;
                C# type errors only show at build time. Config: ariadne.build_gate.
        """
        self.repo_path = Path(repo_path)
        self.python_path = python_path
        self.typecheck_cmd = typecheck_cmd or ["mypy", "--no-error-summary"]
        self.lint_cmd = lint_cmd or ["ruff", "check"]
        self.test_cmd = test_cmd or ["pytest", "-x", "-q"]
        self.require_tests = require_tests
        self.build_gate = build_gate
        self.test_cmds = dict(test_cmds or {})

    def verify(self, diff: Diff, causal_chain: Optional[CausalChain] = None) -> VerificationResult:
        """
        Verify a diff: compile, typecheck, lint, and run the tests matched to it.

        Args:
            diff: The diff to verify
            causal_chain: Pre-computed causal chain (if available)

        Returns:
            VerificationResult with all check outcomes
        """
        import time
        start_time = time.time()

        result = VerificationResult(
            diff_id=diff.id,
            passed=False,
            duration_seconds=0,
        )

        # Create temporary workspace
        with tempfile.TemporaryDirectory(prefix="ariadne-verify-") as tmpdir:
            workspace = Path(tmpdir)

            # Clone repo to workspace (shallow)
            if not self._setup_workspace(workspace, diff):
                result.typecheck_errors = ["Failed to setup verification workspace"]
                result.completed_at = datetime.now(timezone.utc).isoformat()
                result.duration_seconds = time.time() - start_time
                return result

            # Determine scope from causal chain or diff
            if causal_chain:
                modules = causal_chain.affected_modules
                named = list(causal_chain.test_files)
            else:
                modules = self._extract_modules_from_diff(diff)
                named = self._find_tests_for_modules(workspace, modules)

            repo = workspace / "repo"
            changed = sorted(diff.all_affected_files())
            # The palace's call graph of the patched code: tests that reach what changed
            selection = select_tests(repo, diff.content, changed)
            # A changed test file is a test of this diff, whatever its name matches
            changed_tests = [f for f in changed if _is_test_file(f) and (repo / f).exists()]
            test_files = list(dict.fromkeys([*selection.palace, *selection.convention, *named, *changed_tests]))
            result.tests_selected_by = {"palace": selection.palace, "convention": selection.convention,
                                        "name": named, "changed": changed_tests}
            if selection.error:
                result.test_errors.append(selection.error)

            result.modules_checked = modules
            result.tests_executed = test_files

            # Syntax-check every changed file, so a syntax error fails even when no test runs
            self._unchecked = []
            result.compile_passed, result.compile_errors = self._run_compile(
                workspace, diff.all_affected_files()
            )
            if self._unchecked:
                result.skipped_checks.append("syntax (install daedalus[palace] for tree-sitter): "
                                             + ", ".join(self._unchecked))
            if selection.error:
                result.skipped_checks.append(f"palace test selection: {selection.error}")

            # Run type checking: mypy for Python, `dotnet build` for the .NET projects the diff touches
            result.typecheck_passed, result.typecheck_errors = self._run_typecheck(
                workspace, modules
            )
            if self.build_gate and any(f.endswith(BUILD_SOURCES) for f in changed):
                built, build_errors, build_skipped = dotnet_build(repo, changed)
                result.typecheck_passed = result.typecheck_passed and built
                result.typecheck_errors.extend(build_errors)
                result.skipped_checks.extend(build_skipped)

            # Run linting
            result.lint_passed, result.lint_errors = self._run_lint(
                workspace, diff.all_affected_files()
            )

            # Run tests
            ran_nothing = not test_files
            if test_files:
                runs, problems = plan_runs(repo, test_files, self.test_cmd, self.test_cmds)
                result.test_commands = [f"(cd {r.cwd}) {' '.join(r.command)}" for r in runs]
                outcome = run_tests(repo, runs)
                result.tests_passed = outcome.passed
                result.tests_run, result.tests_failed = outcome.ran, outcome.failed
                result.test_errors.extend(problems + outcome.errors)
                # A selected test no runner could run leaves part of the change unverified
                ran_nothing = outcome.ran_nothing or bool(problems)
            if ran_nothing:
                # Nothing checked the behavior, so this is not a pass: fail closed (T-e4). This covers a
                # selection that ran nothing too: files that no longer exist, a package with no tests.
                result.no_tests_matched = True
                if self.require_tests:
                    result.tests_passed = False
                    result.test_errors.append("No tests matched the changed code: not verified" if not test_files
                                              else "Some selected tests did not run: not verified")

        # Overall result
        result.passed = (
            result.compile_passed and
            result.typecheck_passed and
            result.lint_passed and
            result.tests_passed
        )
        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.duration_seconds = time.time() - start_time

        return result

    def _setup_workspace(self, workspace: Path, diff: Diff) -> bool:
        """
        Set up verification workspace by copying repo and applying diff.

        Returns True on success.
        """
        try:
            # Copy repo to workspace (excluding .git for speed if large)
            shutil.copytree(
                self.repo_path,
                workspace / "repo",
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "venv"),
            )

            # Make the copy its own repository. Without this, git looks upward for one: if the temp
            # directory sits inside another repository (a dotfiles repo in the home directory, say),
            # 'git apply' resolves the patch against that repository's root, skips every file outside
            # the current directory, and still exits 0, so verification would test the original code.
            subprocess.run(["git", "init", "-q"], cwd=workspace / "repo", capture_output=True, check=True)

            # Apply diff (newline="" keeps the patch byte-for-byte; text mode on Windows adds \r)
            diff_file = workspace / "changes.diff"
            diff_file.write_text(diff.content, encoding="utf-8", newline="")

            result = subprocess.run(
                ["git", "apply", "--check", str(diff_file)],
                cwd=workspace / "repo",
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Diff doesn't apply cleanly
                return False

            # Actually apply the diff. Fail closed if git skipped any part of it.
            applied = subprocess.run(
                ["git", "apply", "-v", str(diff_file)],
                cwd=workspace / "repo",
                capture_output=True,
                text=True,
                check=True,
            )
            if "Skipped patch" in applied.stdout + applied.stderr:
                return False

            return True

        except Exception as e:
            return False

    def _extract_modules_from_diff(self, diff: Diff) -> List[str]:
        """Extract Python module names from affected files."""
        modules = []
        for filepath in diff.all_affected_files():
            if filepath.endswith(".py"):
                # Convert path to module name
                module = filepath.replace("/", ".").replace("\\", ".")
                if module.endswith(".py"):
                    module = module[:-3]
                if module.startswith("src."):
                    module = module[4:]
                modules.append(module)
        return modules

    def _find_tests_for_modules(self, workspace: Path, modules: List[str]) -> List[str]:
        """Find test files that might test the given modules."""
        test_files = []
        repo = workspace / "repo"

        # Look for test files with matching names
        for module in modules:
            # module.submodule -> test_module.py, test_submodule.py
            parts = module.split(".")
            for part in parts:
                # Check various test naming conventions
                patterns = [
                    f"**/test_{part}.py",
                    f"**/{part}_test.py",
                    f"**/test_{part}*.py",
                    f"tests/**/test_{part}.py",
                ]
                for pattern in patterns:
                    for match in repo.glob(pattern):
                        rel_path = str(match.relative_to(repo))
                        if rel_path not in test_files:
                            test_files.append(rel_path)

        return test_files

    def _run_compile(self, workspace: Path, files: Set[str]) -> tuple[bool, List[str]]:
        """Syntax-check each changed file: compile Python in place (no bytecode written), parse other
        languages with tree-sitter when it's installed. Deleted files are skipped."""
        repo = workspace / "repo"
        errors = []
        for f in sorted(files):
            path = repo / f
            if not path.is_file():
                continue
            if f.endswith(".py"):
                try:
                    compile(path.read_bytes(), f, "exec", dont_inherit=True)
                except (SyntaxError, ValueError) as e:
                    errors.append(f"{f}: {e}")
                continue
            problem = _tree_sitter_syntax_error(path)
            if problem is SYNTAX_UNCHECKED:
                self._unchecked.append(f)
            elif problem:
                errors.append(f"{f}: {problem}")
        return not errors, errors

    def _run_typecheck(
        self,
        workspace: Path,
        modules: List[str],
    ) -> tuple[bool, List[str]]:
        """Run type checking on specified modules."""
        if not modules:
            return True, []

        repo = workspace / "repo"

        # Convert modules to file paths for mypy
        files = []
        for module in modules:
            # Try to find the actual file
            path = module.replace(".", "/") + ".py"
            if (repo / path).exists():
                files.append(path)
            elif (repo / "src" / path).exists():
                files.append(f"src/{path}")

        if not files:
            return True, []

        try:
            result = subprocess.run(
                self.typecheck_cmd + files,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=60,
            )

            errors = []
            if result.returncode != 0:
                errors = [line for line in result.stdout.split("\n") if line.strip()]

            return result.returncode == 0, errors

        except subprocess.TimeoutExpired:
            return False, ["Type checking timed out"]
        except FileNotFoundError:
            # mypy not installed - skip
            return True, []

    def _run_lint(
        self,
        workspace: Path,
        files: Set[str],
    ) -> tuple[bool, List[str]]:
        """Run linting on specified files."""
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return True, []

        repo = workspace / "repo"

        # Filter to files that exist
        existing = [f for f in py_files if (repo / f).exists()]
        if not existing:
            return True, []

        try:
            result = subprocess.run(
                self.lint_cmd + existing,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=30,
            )

            errors = []
            if result.returncode != 0:
                errors = [line for line in result.stdout.split("\n") if line.strip()]

            return result.returncode == 0, errors

        except subprocess.TimeoutExpired:
            return False, ["Linting timed out"]
        except FileNotFoundError:
            # ruff not installed - skip
            return True, []


def _is_test_file(path: str) -> bool:
    """Test code by its language's conventions (test_*.py, *_test.go, *.test.ts, src/test/..., spec/...)."""
    from ..labyrinth.query import in_test_file
    path = path.replace("\\", "/")
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        return name.startswith("test_") or name.endswith("_test.py")
    return in_test_file(path)


def _language_of(path: str):
    from ..labyrinth.query import _language
    return _language(path)


SYNTAX_UNCHECKED = "unchecked"


def _tree_sitter_syntax_error(path: Path) -> Optional[str]:
    """The first parse error tree-sitter finds in a non-Python file, or None (also when the language isn't
    analyzed or tree-sitter isn't installed)."""
    from ..labyrinth.languages import get_language_registry
    from ..labyrinth.treesitter import TreeSitterSupport

    support = get_language_registry().get_by_extension(path)
    if not isinstance(support, TreeSitterSupport) or not support.available():
        # A language the palace knows of but can't parse here (no tree-sitter) is unchecked, not clean
        from ..labyrinth.treesitter import GRAMMARS
        return SYNTAX_UNCHECKED if any(path.suffix in g.extensions for g in GRAMMARS) else None
    try:
        _, tree = support._parse(path)
    except OSError:
        return None
    if not tree.root_node.has_error:
        return None
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            return f"syntax error at line {node.start_point[0] + 1}"
        stack.extend(reversed([c for c in node.children if c.has_error or c.is_missing or c.type == "ERROR"]))
    return "syntax error"


def extract_causal_chain(diff: Diff, repo_path: Path) -> CausalChain:
    """
    Extract the causal chain from a diff: the files and definitions it touches, their modules, and the
    tests likely to cover them.

    Definitions and tests come from the palace's call graph of `repo_path` (the worker's directory,
    where the change is applied; at the orchestrator, the base). For Python the older name-based
    extraction (def/class lines, tests/test_<part>.py) is kept alongside, so nothing it found is lost.
    """
    from ..labyrinth.sources import module_id

    affected_files = list(diff.all_affected_files())

    # Definitions the diff touches, by the palace (any language), plus Python def/class lines it adds
    affected_functions: List[str] = []
    selection = select_tests(Path(repo_path), diff.content, sorted(affected_files))
    affected_functions.extend(n.rsplit(".", 1)[-1] for n in selection.changed_nodes)
    for line in diff.content.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            func_match = re.match(r"\+\s*def\s+(\w+)", line)
            class_match = re.match(r"\+\s*class\s+(\w+)", line)
            if func_match:
                affected_functions.append(func_match.group(1))
            elif class_match:
                affected_functions.append(class_match.group(1))
    affected_functions = list(dict.fromkeys(affected_functions))

    # Module names: dotted for Python (as before), the palace's module ids for other languages
    affected_modules = []
    python_modules = []
    for filepath in affected_files:
        if filepath.endswith(".py"):
            module = filepath.replace("/", ".").replace("\\", ".")
            if module.endswith(".py"):
                module = module[:-3]
            affected_modules.append(module)
            python_modules.append(module)
        elif _language_of(filepath):
            affected_modules.append(module_id(Path(filepath)))

    # Tests: the palace's selection, then the older Python name patterns
    test_files = list(selection.files)
    for module in python_modules:
        for part in module.split("."):
            for pattern in (f"tests/test_{part}.py", f"test_{part}.py", f"tests/{part}_test.py"):
                if (repo_path / pattern).exists() and pattern not in test_files:
                    test_files.append(pattern)

    return CausalChain(
        diff_id=diff.id,
        affected_files=affected_files,
        affected_functions=affected_functions,
        affected_modules=affected_modules,
        call_depth=6 if selection.changed_nodes else 1,  # the palace follows call chains up to 6 deep
        test_files=test_files,
    )
