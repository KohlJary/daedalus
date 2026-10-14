"""daedalus palace callers|callees|impact|path|tests-for: fast, read-only call-graph queries."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.labyrinth.query import build_query_graph, resolve_symbol

CORE = '''def _helper():
    return 1


def compute(x):
    return _helper() + x


class Engine:
    def run(self):
        return compute(1)
'''
OTHER = '''from pkg.core import Engine


def start():
    return Engine().run()


def unrelated():
    return 0
'''
TESTS = '''from pkg.core import compute
from pkg.other import start


def test_compute():
    assert compute(2) == 3


def test_start():
    assert start() == 2
'''
TESTS_OTHER = '''from pkg.other import unrelated


def test_unrelated():
    assert unrelated() == 0
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "core.py").write_text(CORE)
    (root / "pkg" / "other.py").write_text(OTHER)
    (root / "tests" / "test_core.py").write_text(TESTS)
    (root / "tests" / "test_unrelated.py").write_text(TESTS_OTHER)
    for args in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    monkeypatch.chdir(root)
    return root


def run(*args):
    result = CliRunner().invoke(main, ["palace", *args])
    return result.exit_code, result.output


def test_private_helpers_are_in_the_graph(project):
    # The palace's room builder drops private methods; the query graph must not, or chains through them break.
    graph = build_query_graph(project).graph
    assert resolve_symbol(graph, "_helper") == ["pkg.core._helper"]


def test_callers_and_callees(project):
    code, out = run("callers", "_helper")
    assert code == 0 and "pkg.core.compute" in out
    code, out = run("callees", "Engine.run")
    assert code == 0 and "pkg.core.compute" in out


def test_method_called_through_an_instance_is_linked(project):
    # Engine().run() is recorded by bare name 'run'; it still has to reach Engine.run
    code, out = run("callers", "Engine.run")
    assert code == 0 and "pkg.other.start" in out


def test_impact_with_tests(project):
    code, out = run("impact", "_helper", "--tests")
    assert code == 0
    assert "tests/test_core.py" in out and "tests/test_unrelated.py" not in out
    data = json.loads(run("impact", "_helper", "--tests", "--json")[1])
    assert {"tests.test_core.test_compute", "tests.test_core.test_start"} <= set(data["tests"])


def test_path(project):
    code, out = run("path", "start", "_helper")
    assert code == 0 and "start -> run -> compute -> _helper" in out


def test_ambiguous_and_unknown_symbols(project):
    (project / "pkg" / "dup.py").write_text("def compute():\n    return 0\n")
    code, out = run("callers", "compute")
    assert code == 2 and "pkg.core.compute" in out and "pkg.dup.compute" in out
    code, out = run("callers", "core.compute")
    assert code == 0
    code, _ = run("callers", "nothing_like_this")
    assert code == 1


def test_tests_for_file(project):
    code, out = run("tests-for", "pkg/core.py")
    assert code == 0 and "tests/test_core.py" in out and "tests/test_unrelated.py" not in out


def test_tests_for_diff(project):
    core = project / "pkg" / "core.py"
    core.write_text(core.read_text().replace("return 1", "return 2"))  # inside _helper
    data = json.loads(run("tests-for", "--diff", "--json")[1])
    assert data["symbols"] == ["pkg.core._helper"]
    assert data["test_files"] == ["tests/test_core.py"] and data["full_suite_recommended"] is False


def test_tests_for_diff_includes_new_untracked_files(project):
    (project / "pkg" / "fresh.py").write_text("from pkg.other import unrelated\n\n\ndef wrapper():\n    return unrelated()\n")
    data = json.loads(run("tests-for", "--diff", "--json")[1])
    assert "pkg.fresh.wrapper" in data["symbols"]


def test_no_tests_found_recommends_the_full_suite(project):
    (project / "pkg" / "lonely.py").write_text("def alone():\n    return 1\n")
    code, out = run("tests-for", "pkg/lonely.py")
    assert code == 0 and "Run the full suite" in out
    assert json.loads(run("tests-for", "pkg/lonely.py", "--json")[1])["full_suite_recommended"] is True


def test_queries_never_create_palace_storage(project):
    run("impact", "_helper", "--tests")
    run("tests-for", "--diff")
    assert not (project / ".mind-palace").exists()


# --- the design rules, each with a test that fails if the rule is removed ---

def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_bare_names_past_the_cap_are_not_linked_and_say_so(project):
    write(project, "pkg/many.py", "".join(f"class K{i}:\n    def get(self):\n        return {i}\n\n\n" for i in range(11)))
    write(project, "pkg/user.py", "def fetch(o):\n    return o.get()\n")
    code, out = run("callers", "K3.get")
    assert code == 0 and "(none found)" in out and "11 definitions" in out
    code, out = run("callees", "fetch")
    assert "(none found)" in out and "get (11)" in out


def test_past_the_cap_same_module_definitions_still_link(project):
    write(project, "pkg/many.py", "".join(f"class K{i}:\n    def get(self):\n        return {i}\n\n\n" for i in range(11)))
    # o.get() past the cap: only the caller's own module's definition is linked
    write(project, "pkg/local.py", "class Local:\n    def get(self):\n        return 0\n\n\ndef fetch(o):\n    return o.get()\n")
    code, out = run("callees", "local.fetch")
    assert "pkg.local.Local.get" in out and "K3.get" not in out


def test_within_the_cap_every_definition_links_including_same_module(project):
    # o.run() through an object: a same-module function must not hide same-named methods elsewhere
    write(project, "pkg/a.py", "class Foo:\n    def run(self):\n        return 1\n\n\nclass Bar:\n    def run(self):\n        return 2\n")
    write(project, "pkg/b.py", "def run():\n    return 3\n\n\ndef caller(o):\n    return o.run()\n")
    code, out = run("callees", "b.caller")
    assert {"pkg.a.Foo.run", "pkg.a.Bar.run", "pkg.b.run"} <= set(line.split()[0] for line in out.splitlines() if line.startswith("    "))


def test_construction_reaches_the_constructor(project):
    write(project, "pkg/ctor.py", "def helper():\n    return 1\n\n\nclass Foo:\n    def __init__(self):\n        self.x = helper()\n\n\ndef make():\n    return Foo()\n")
    write(project, "tests/test_ctor.py", "from pkg.ctor import make\n\n\ndef test_make():\n    assert make().x == 1\n")
    data = json.loads(run("impact", "ctor.helper", "--tests", "--json")[1])
    assert "tests.test_ctor.test_make" in data["tests"]
    code, out = run("callers", "Foo.__init__")
    assert "constructed by" in out and "pkg.ctor.make" in out


def test_a_change_between_functions_touches_no_function(project):
    core = project / "pkg" / "core.py"
    core.write_text(core.read_text().replace("def compute(x):", "LIMIT = 5\n\n\ndef compute(x):"))
    data = json.loads(run("tests-for", "--diff", "--json")[1])
    assert data["symbols"] == [] and data["full_suite_recommended"] is True


def test_changes_in_two_adjacent_functions_map_to_both(project):
    core = project / "pkg" / "core.py"
    core.write_text(core.read_text().replace("return 1", "return 7").replace("return _helper() + x", "return _helper() + x + 0"))
    data = json.loads(run("tests-for", "--diff", "--json")[1])
    assert data["symbols"] == ["pkg.core._helper", "pkg.core.compute"]


def test_a_change_inside_a_method_maps_to_the_method_not_its_class(project):
    core = project / "pkg" / "core.py"
    core.write_text(core.read_text().replace("return compute(1)", "return compute(2)"))
    assert json.loads(run("tests-for", "--diff", "--json")[1])["symbols"] == ["pkg.core.Engine.run"]


def test_convention_named_tests_are_listed_without_call_edges(project):
    write(project, "pkg/conv.py", "def lonely():\n    return 1\n")
    write(project, "tests/test_conv.py", "def test_nothing_imported():\n    assert True\n")
    code, out = run("tests-for", "pkg/conv.py")
    assert "tests/test_conv.py" in out


def test_diff_outside_a_git_repo_is_an_error_not_zero_changes(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    write(plain, "m.py", "def f():\n    return 1\n")
    monkeypatch.chdir(plain)
    code, out = run("tests-for", "--diff")
    assert code == 3 and "Can't read the changes" in out


def test_bad_base_is_an_error(project):
    code, out = run("tests-for", "--diff", "--base", "no-such-ref")
    assert code == 3


def test_diff_from_a_subdirectory_uses_the_repo_root(project, monkeypatch):
    core = project / "pkg" / "core.py"
    core.write_text(core.read_text().replace("return 1", "return 2"))
    monkeypatch.chdir(project / "pkg")
    assert json.loads(run("tests-for", "--diff", "--json")[1])["symbols"] == ["pkg.core._helper"]


def test_paths_outside_the_project_or_missing_are_errors(project):
    assert run("tests-for", "/etc/hostname")[0] == 1
    assert run("tests-for", "pkg/nope.py")[0] == 1


def test_path_depth_counts_hops(project):
    chain = "".join(f"def f{i}():\n    return f{i + 1}()\n\n\n" for i in range(10)) + "def f10():\n    return 0\n"
    write(project, "pkg/chain.py", chain)
    assert "(10 hops)" in run("path", "chain.f0", "chain.f10", "--depth", "10")[1]
    assert "none within 9 hops" in run("path", "chain.f0", "chain.f10", "--depth", "9")[1]


def test_a_plain_call_links_only_the_local_function(project):
    write(project, "pkg/a.py", "class Foo:\n    def run(self):\n        return 1\n")
    write(project, "pkg/b.py", "def run():\n    return 3\n\n\ndef plain_caller():\n    return run()\n")
    code, out = run("callees", "b.plain_caller")
    linked = {line.split()[0] for line in out.splitlines() if line.startswith("    ")}
    assert linked == {"pkg.b.run"}
