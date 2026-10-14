"""
Diff Verification

Ariadne's mechanical gate. Each worker diff is applied to a fresh copy of the whole repository
(not a slice of it) and checked there. What is narrowed is which checks run: the tests are chosen
by name from the modules the diff touches, not from a call graph. The name "causal slice" is the
goal; the Palace call graph (`daedalus palace tests-for`) is not wired in yet.

Flow:
1. Copy the repository to a temp workspace and apply the diff
2. Compile every changed Python file (a syntax gate that runs even when no test does)
3. Type check and lint the changed modules
4. Run the tests matched by name to the changed modules, plus any changed test files
5. If no test matched, the diff is not verified (`no_tests_matched`): it fails closed, and the
   orchestrator routes it to human review instead of merging it (gameplan T-e4, issue #15)
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
            },
            "scope": {
                "modules": self.modules_checked,
                "tests": self.tests_executed,
            },
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
    ):
        """
        Initialize verifier.

        Args:
            repo_path: Path to the git repository
            python_path: Python interpreter to use
            typecheck_cmd: Command for type checking (default: mypy)
            lint_cmd: Command for linting (default: ruff)
            test_cmd: Command for running tests (default: pytest)
            require_tests: A diff no test matched is not verified (default). False lets it pass
                on the other checks alone; for harnesses that stub the test command out.
        """
        self.repo_path = Path(repo_path)
        self.python_path = python_path
        self.typecheck_cmd = typecheck_cmd or ["mypy", "--no-error-summary"]
        self.lint_cmd = lint_cmd or ["ruff", "check"]
        self.test_cmd = test_cmd or ["pytest", "-x", "-q"]
        self.require_tests = require_tests

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
                test_files = causal_chain.test_files
            else:
                modules = self._extract_modules_from_diff(diff)
                test_files = self._find_tests_for_modules(workspace, modules)

            # A changed test file is a test of this diff, whatever its name matches
            repo = workspace / "repo"
            changed_tests = [f for f in sorted(diff.all_affected_files())
                             if _is_test_file(f) and (repo / f).exists()]
            test_files = list(dict.fromkeys([*test_files, *changed_tests]))

            result.modules_checked = modules
            result.tests_executed = test_files

            # Compile every changed Python file, so a syntax error fails even when no test runs
            result.compile_passed, result.compile_errors = self._run_compile(
                workspace, diff.all_affected_files()
            )

            # Run type checking
            result.typecheck_passed, result.typecheck_errors = self._run_typecheck(
                workspace, modules
            )

            # Run linting
            result.lint_passed, result.lint_errors = self._run_lint(
                workspace, diff.all_affected_files()
            )

            # Run tests
            if test_files:
                result.tests_passed, result.tests_run, result.tests_failed, result.test_errors = (
                    self._run_tests(workspace, test_files)
                )
            else:
                # Nothing checked the behavior, so this is not a pass: fail closed (T-e4)
                result.no_tests_matched = True
                if self.require_tests:
                    result.tests_passed = False
                    result.test_errors = ["No tests matched the changed modules: not verified"]

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
        """Compile each changed Python file in place (no bytecode written). Deleted files are skipped."""
        repo = workspace / "repo"
        errors = []
        for f in sorted(files):
            path = repo / f
            if not f.endswith(".py") or not path.is_file():
                continue
            try:
                compile(path.read_bytes(), f, "exec", dont_inherit=True)
            except (SyntaxError, ValueError) as e:
                errors.append(f"{f}: {e}")
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

    def _run_tests(
        self,
        workspace: Path,
        test_files: List[str],
    ) -> tuple[bool, int, int, List[str]]:
        """
        Run specified tests.

        Returns: (passed, total_run, failed_count, error_messages)
        """
        if not test_files:
            return True, 0, 0, []

        repo = workspace / "repo"

        # Filter to existing test files
        existing = [f for f in test_files if (repo / f).exists()]
        if not existing:
            return True, 0, 0, []

        try:
            result = subprocess.run(
                self.test_cmd + existing,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Parse pytest output for counts
            # Look for "X passed" or "X failed" in output
            passed_match = re.search(r"(\d+) passed", result.stdout)
            failed_match = re.search(r"(\d+) failed", result.stdout)

            passed_count = int(passed_match.group(1)) if passed_match else 0
            failed_count = int(failed_match.group(1)) if failed_match else 0
            total = passed_count + failed_count

            errors = []
            if result.returncode != 0:
                # Extract failure info
                errors = [line for line in result.stdout.split("\n")
                         if "FAILED" in line or "ERROR" in line]

            return result.returncode == 0, total, failed_count, errors

        except subprocess.TimeoutExpired:
            return False, 0, 0, ["Tests timed out"]
        except FileNotFoundError:
            return False, 0, 0, ["pytest not found"]


def _is_test_file(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def extract_causal_chain(diff: Diff, repo_path: Path) -> CausalChain:
    """
    Extract the causal chain from a diff.

    This is a simplified version - full implementation would integrate
    with the Palace/Labyrinth pathfinding for accurate call graph analysis.

    For now, we do basic extraction:
    - Files affected directly
    - Functions modified (parsed from diff)
    - Modules touched
    - Tests that likely cover this code
    """
    affected_files = list(diff.all_affected_files())

    # Extract function names from diff (look for def/class lines)
    affected_functions = []
    for line in diff.content.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            # Look for function/class definitions
            func_match = re.match(r"\+\s*def\s+(\w+)", line)
            class_match = re.match(r"\+\s*class\s+(\w+)", line)
            if func_match:
                affected_functions.append(func_match.group(1))
            elif class_match:
                affected_functions.append(class_match.group(1))

    # Extract module names
    affected_modules = []
    for filepath in affected_files:
        if filepath.endswith(".py"):
            module = filepath.replace("/", ".").replace("\\", ".")
            if module.endswith(".py"):
                module = module[:-3]
            affected_modules.append(module)

    # Find test files
    test_files = []
    for module in affected_modules:
        parts = module.split(".")
        for part in parts:
            test_patterns = [
                f"tests/test_{part}.py",
                f"test_{part}.py",
                f"tests/{part}_test.py",
            ]
            for pattern in test_patterns:
                if (repo_path / pattern).exists():
                    test_files.append(pattern)

    return CausalChain(
        diff_id=diff.id,
        affected_files=affected_files,
        affected_functions=affected_functions,
        affected_modules=affected_modules,
        call_depth=1,  # Basic extraction doesn't follow call graph
        test_files=test_files,
    )
