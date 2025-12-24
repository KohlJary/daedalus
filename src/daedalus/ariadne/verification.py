"""
Causal Slice Verification

The key innovation of Ariadne: instead of running the full test suite for each
worker's changes, we verify only the "causal slice" - the code paths affected
by the changes.

This enables fast feedback (seconds instead of minutes) while still catching
real issues.

Flow:
1. Extract causal chain from diff (what functions/modules are affected)
2. Find tests that touch the affected code
3. Run only those tests
4. Type check only affected modules
5. Return verification result
"""

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
    """Result of causal slice verification."""
    diff_id: str
    passed: bool
    duration_seconds: float

    # Individual check results
    typecheck_passed: bool = True
    typecheck_errors: List[str] = field(default_factory=list)

    lint_passed: bool = True
    lint_errors: List[str] = field(default_factory=list)

    tests_passed: bool = True
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
            "tests": {
                "passed": self.tests_passed,
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
    Verifies diffs by checking only the affected code paths.

    Instead of running the full test suite, we:
    1. Apply the diff to a temporary workspace
    2. Identify affected modules from the causal chain
    3. Type check only those modules
    4. Lint only those files
    5. Run only tests that touch the affected code
    """

    def __init__(
        self,
        repo_path: Path,
        python_path: str = "python",
        typecheck_cmd: Optional[List[str]] = None,
        lint_cmd: Optional[List[str]] = None,
        test_cmd: Optional[List[str]] = None,
    ):
        """
        Initialize verifier.

        Args:
            repo_path: Path to the git repository
            python_path: Python interpreter to use
            typecheck_cmd: Command for type checking (default: mypy)
            lint_cmd: Command for linting (default: ruff)
            test_cmd: Command for running tests (default: pytest)
        """
        self.repo_path = Path(repo_path)
        self.python_path = python_path
        self.typecheck_cmd = typecheck_cmd or ["mypy", "--no-error-summary"]
        self.lint_cmd = lint_cmd or ["ruff", "check"]
        self.test_cmd = test_cmd or ["pytest", "-x", "-q"]

    def verify(self, diff: Diff, causal_chain: Optional[CausalChain] = None) -> VerificationResult:
        """
        Verify a diff using causal slice checking.

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

            result.modules_checked = modules
            result.tests_executed = test_files

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
                # No tests to run - that's okay for some changes
                result.tests_passed = True

        # Overall result
        result.passed = (
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

            # Apply diff
            diff_file = workspace / "changes.diff"
            diff_file.write_text(diff.content)

            result = subprocess.run(
                ["git", "apply", "--check", str(diff_file)],
                cwd=workspace / "repo",
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Diff doesn't apply cleanly
                return False

            # Actually apply the diff
            subprocess.run(
                ["git", "apply", str(diff_file)],
                cwd=workspace / "repo",
                capture_output=True,
                check=True,
            )

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
            import re
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
    import re
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
