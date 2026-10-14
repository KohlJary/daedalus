"""Ariadne's verifier beyond Python (T-e22): palace test selection, each language's runner, a syntax gate
for every language, and no vacuous passes."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.ariadne.diff_bus import Diff
from daedalus.ariadne.test_runners import plan_runs
from daedalus.ariadne.verification import CausalSliceVerifier, extract_causal_chain
from daedalus.labyrinth import languages

NOOP = [sys.executable, "-c", "pass"]


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo.parent if False else repo, "init", "-q") if (repo / ".git").exists() else subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    languages._registry = None
    return repo


def diff_for(repo, path, content):
    """The diff that would change `path` to `content`, leaving the repo as it was."""
    target = repo / path
    original = target.read_text() if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", "-N", path)
    text = git(repo, "diff", "--", path)
    if original is None:
        git(repo, "rm", "-q", "--cached", path)
        target.unlink()
    else:
        target.write_text(original)
    return Diff.from_git_diff("wp-1", "w-1", text, "change")


def verifier(repo, **kw):
    return CausalSliceVerifier(repo, typecheck_cmd=NOOP, lint_cmd=NOOP, **kw)


GO = {
    "go.mod": "module example.com/calc\n\ngo 1.21\n",
    "calc/calc.go": "package calc\n\nfunc Double(x int) int { return helper(x) }\n\nfunc helper(x int) int { return x * 2 }\n",
    "calc/calc_test.go": "package calc\n\nimport \"testing\"\n\nfunc TestDouble(t *testing.T) {\n\tif Double(2) != 4 {\n\t\tt.Fatal(\"bad\")\n\t}\n}\n",
    "notest/util.go": "package notest\n\nfunc Util() int { return 1 }\n",
}


@pytest.mark.skipif(shutil.which("go") is None, reason="needs go")
def test_go_diff_is_verified_by_the_tests_that_reach_it(tmp_path):
    pytest.importorskip("tree_sitter_go")
    repo = make_repo(tmp_path, GO)
    good = diff_for(repo, "calc/calc.go", GO["calc/calc.go"].replace("x * 2", "x + x"))
    result = verifier(repo).verify(good)
    assert result.passed, result.to_dict()
    assert "calc/calc_test.go" in result.tests_selected_by["palace"]  # helper -> Double -> TestDouble
    assert result.tests_run == 1 and any("go test" in c for c in result.test_commands)

    broken = diff_for(repo, "calc/calc.go", GO["calc/calc.go"].replace("x * 2", "x * 3"))
    result = verifier(repo).verify(broken)
    assert not result.passed and not result.tests_passed and result.tests_failed == 1


@pytest.mark.skipif(shutil.which("go") is None, reason="needs go")
def test_a_go_package_without_tests_is_not_verified(tmp_path):
    pytest.importorskip("tree_sitter_go")
    repo = make_repo(tmp_path, GO)
    result = verifier(repo).verify(diff_for(repo, "notest/util.go", GO["notest/util.go"].replace("1", "2")))
    assert not result.passed and result.no_tests_matched and result.tests_run == 0


def test_selected_test_files_that_no_longer_exist_do_not_pass(tmp_path):
    repo = make_repo(tmp_path, {"app/core.py": "def f():\n    return 1\n"})
    from daedalus.ariadne.diff_bus import CausalChain
    chain = CausalChain(diff_id="d", affected_files=["app/core.py"], affected_functions=[], affected_modules=["app.core"],
                        call_depth=1, test_files=["tests/test_gone.py"])
    result = verifier(repo, test_cmd=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]).verify(
        diff_for(repo, "app/core.py", "def f():\n    return 2\n"), chain)
    # it used to report tests_passed with nothing run
    assert not result.passed and result.no_tests_matched and result.tests_run == 0
    assert any("none of the selected test files exist" in e for e in result.test_errors)


@pytest.mark.skipif(shutil.which("cargo") is None, reason="needs cargo")
def test_rust_unit_tests_run_through_cargo(tmp_path):
    pytest.importorskip("tree_sitter_rust")
    files = {
        "Cargo.toml": "[package]\nname = \"calc\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[dependencies]\n",
        "src/lib.rs": "pub fn double(x: i32) -> i32 { helper(x) }\nfn helper(x: i32) -> i32 { x * 2 }\n\n"
                      "#[cfg(test)]\nmod tests {\n    use super::*;\n    #[test]\n    fn doubles() { assert_eq!(double(2), 4); }\n}\n",
    }
    repo = make_repo(tmp_path, files)
    result = verifier(repo).verify(diff_for(repo, "src/lib.rs", files["src/lib.rs"].replace("x * 2", "x + x")))
    assert result.passed, result.to_dict()
    assert result.tests_run == 1 and any("cargo test --lib" in c for c in result.test_commands)


def test_syntax_errors_fail_in_any_language(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    pytest.importorskip("tree_sitter_javascript")
    repo = make_repo(tmp_path, {"src/a.ts": "export function f(x: number) { return x; }\n"})
    result = verifier(repo, require_tests=False).verify(diff_for(repo, "src/a.ts", "export function f(x: number { return x; }\n"))
    assert not result.compile_passed and "src/a.ts: syntax error at line 1" in result.compile_errors[0]


def test_runner_plans_per_ecosystem(tmp_path):
    repo = tmp_path
    (repo / "web").mkdir()
    (repo / "web/package.json").write_text(json.dumps({"devDependencies": {"vitest": "^1"}}))
    (repo / "api").mkdir()
    (repo / "api/package.json").write_text(json.dumps({"devDependencies": {"jest": "^29"}}))
    (repo / "svc").mkdir()
    (repo / "svc/pom.xml").write_text("<project/>")
    (repo / "mob").mkdir()
    (repo / "mob/build.gradle").write_text("")
    languages._registry = None
    files = ["web/src/a.test.ts", "api/b.test.js", "svc/src/test/java/x/FooTest.java", "mob/src/test/java/BarTest.java",
             "spec/thing_spec.rb", "tests/test_x.py"]
    runs, problems = plan_runs(repo, files, ["pytest", "-q"])
    commands = {(r.cwd, " ".join(r.command)) for r in runs}
    if pytest.importorskip.__module__ and _has("tree_sitter_typescript", "tree_sitter_java", "tree_sitter_ruby"):
        assert ("web", "npx --no-install vitest run src/a.test.ts") in commands
        assert ("api", "npx --no-install jest b.test.js") in commands
        assert ("svc", "mvn -q test -Dtest=FooTest -Dsurefire.failIfNoSpecifiedTests=false") in commands
        assert ("mob", "gradle test --tests BarTest") in commands
        assert (".", "bundle exec rspec spec/thing_spec.rb") in commands
    assert (".", "pytest -q tests/test_x.py") in commands
    assert problems == []


def test_unknown_runners_are_reported_and_overrides_win(tmp_path):
    runs, problems = plan_runs(tmp_path, ["tests/test_x.py"], ["pytest"], {"Python": ["tox", "--"]})
    assert [" ".join(r.command) for r in runs] == ["tox -- tests/test_x.py"]
    if _has("tree_sitter_language_pack"):
        _, problems = plan_runs(tmp_path, ["src/test/scala/FooSpec.scala"], ["pytest"])
        assert problems and "Scala" in problems[0]


def test_causal_chain_names_definitions_and_tests_in_any_language(tmp_path):
    pytest.importorskip("tree_sitter_go")
    repo = make_repo(tmp_path, GO)
    diff = diff_for(repo, "calc/calc.go", GO["calc/calc.go"].replace("x * 2", "x + x"))
    (repo / "calc/calc.go").write_text(GO["calc/calc.go"].replace("x * 2", "x + x"))  # the worker's tree has it
    chain = extract_causal_chain(diff, repo)
    assert "helper" in chain.affected_functions
    assert "calc/calc_test.go" in chain.test_files
    assert chain.affected_modules == ["calc.calc.go"]


def _has(*modules):
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in modules)
