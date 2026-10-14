"""Import-aware call resolution (T-e23): a call bound by an import resolves to exactly that definition, a
call bound to code outside the project links to nothing, and everything else keeps the name-based rules."""

import subprocess

import pytest

from daedalus.labyrinth import languages
from daedalus.labyrinth.query import build_query_graph


def graph(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return build_query_graph(tmp_path).graph


def test_python_from_import_picks_the_imported_definition(tmp_path):
    g = graph(tmp_path, {
        "app/a.py": "def save():\n    pass\n",
        "app/b.py": "def save():\n    pass\n",
        "app/use.py": "from app.a import save\n\ndef run():\n    save()\n",
    })
    assert g.nodes["app.use.run"].calls == ["app.a.save"]  # name-based alone would link both saves


def test_python_module_alias_relative_import_and_reexport(tmp_path):
    g = graph(tmp_path, {
        "pkg/__init__.py": "from .core import build\n",
        "pkg/core.py": "def build():\n    pass\n",
        "pkg/other.py": "def build():\n    pass\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/tool.py": "from .. import core as c\nfrom pkg import build\n\n"
                           "def one():\n    c.build()\n\ndef two():\n    build()\n",
    })
    assert g.nodes["pkg.sub.tool.one"].calls == ["pkg.core.build"]  # module alias via a relative import
    assert g.nodes["pkg.sub.tool.two"].calls == ["pkg.core.build"]  # re-exported through pkg/__init__.py


def test_python_submodule_of_an_empty_package(tmp_path):
    g = graph(tmp_path, {
        "lib/__init__.py": "",
        "lib/harness.py": "def load():\n    pass\n",
        "lib/fake.py": "def load():\n    pass\n",
        "tests/test_h.py": "from lib import harness\n\ndef test_load():\n    harness.load()\n",
    })
    # an __init__.py with no definitions still makes `lib` part of the project
    assert g.nodes["tests.test_h.test_load"].calls == ["lib.harness.load"]


def test_python_calls_into_external_modules_link_nothing(tmp_path):
    g = graph(tmp_path, {
        "app/codec.py": "def dumps(x):\n    return x\n",
        "app/use.py": "import json\nfrom os.path import join\n\n"
                      "def run(d):\n    json.dumps(d)\n    join('a', 'b')\n",
        "app/paths.py": "def join(a, b):\n    return a\n",
    })
    assert g.nodes["app.use.run"].calls == []  # json.dumps and os.path.join are not the project's


def test_python_calls_through_objects_keep_the_name_based_fallback(tmp_path):
    g = graph(tmp_path, {
        "app/store.py": "class Store:\n    def save(self):\n        pass\n",
        "app/use.py": "def run(store):\n    store.save()\n",
    })
    assert g.nodes["app.use.run"].calls == ["app.store.Store.save"]


def test_python_ambiguous_module_names_fall_back(tmp_path):
    g = graph(tmp_path, {
        "x/config.py": "def load():\n    pass\n",
        "y/config.py": "def load():\n    pass\n",
        "z/use.py": "from config import load\n\ndef run():\n    load()\n",
    })
    # two config.py files and neither is nearer: imports don't decide, the name-based rule links both
    assert sorted(g.nodes["z.use.run"].calls) == ["x.config.load", "y.config.load"]


def test_typescript_named_namespace_and_default_imports(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    pytest.importorskip("tree_sitter_javascript")
    g = graph(tmp_path, {
        "src/a.ts": "export function fmt(x: number) { return x; }\n",
        "src/b.ts": "export function fmt(x: number) { return x; }\n",
        "src/util/index.ts": "export function slug(s: string) { return s; }\n",
        "src/main.ts": "import { fmt as f } from './a';\nimport * as u from './util';\nimport lodash from 'lodash';\n"
                       "export function run() { f(1); u.slug('x'); lodash.fmt(2); }\n",
        "package.json": '{"dependencies": {"lodash": "^4"}}',
    })
    assert sorted(g.nodes["src.main.ts.run"].calls) == ["src.a.ts.fmt", "src.util.index.ts.slug"]


def test_typescript_bare_imports_that_are_not_dependencies_fall_back(tmp_path):
    pytest.importorskip("tree_sitter_typescript")
    pytest.importorskip("tree_sitter_javascript")
    g = graph(tmp_path, {
        "src/lib/x.ts": "export function named() { return 1; }\n",
        "src/main.ts": "import { named } from '@/lib/x';\nimport { core } from '@org/core';\nexport function run() { named(); core(); }\n",
        "packages/core/index.ts": "export function core() { return 2; }\n",
        "package.json": '{"dependencies": {"react": "^18"}}',
    })
    # '@/lib/x' is a tsconfig path alias and '@org/core' a workspace package: not dependencies, so they
    # aren't treated as external; the name-based rule still links them
    assert sorted(g.nodes["src.main.ts.run"].calls) == ["packages.core.index.ts.core", "src.lib.x.ts.named"]


def test_python_namespace_packages_and_exact_absolute_imports(tmp_path):
    g = graph(tmp_path, {
        "ns/helper.py": "def h():\n    pass\n",
        "ns/sub/impl.py": "def g():\n    pass\n",
        "config.py": "def load():\n    pass\n",
        "app/__init__.py": "",
        "app/config.py": "def load():\n    pass\n",
        "app/views.py": "from ns import helper\nfrom ns.sub import impl\nfrom config import load\n\n"
                        "def a():\n    helper.h()\n\ndef b():\n    impl.g()\n\ndef c():\n    load()\n",
    })
    assert g.nodes["app.views.a"].calls == ["ns.helper.h"]       # ns/ has no __init__.py
    assert g.nodes["app.views.b"].calls == ["ns.sub.impl.g"]
    assert g.nodes["app.views.c"].calls == ["config.load"]       # absolute: the root config.py, not app/config.py


def test_python_twice_imported_names_and_local_defs_are_left_undecided(tmp_path):
    g = graph(tmp_path, {
        "a.py": "def run():\n    pass\n",
        "b.py": "def run():\n    pass\n",
        "c.py": "try:\n    from a import run\nexcept ImportError:\n    from b import run\n\ndef go():\n    run()\n",
        "d.py": "from a import helper\n\ndef helper():\n    pass\n\ndef go():\n    helper()\n",
    })
    assert sorted(g.nodes["c.go"].calls) == ["a.run", "b.run"]
    assert g.nodes["d.go"].calls == ["d.helper"]


def test_java_nested_class_imports_fall_back(tmp_path):
    pytest.importorskip("tree_sitter_java")
    g = graph(tmp_path, {
        "src/com/x/Outer.java": "package com.x;\npublic class Outer { public static class Inner { public static void go() {} } }\n",
        "src/com/y/App.java": "package com.y;\nimport com.x.Outer.Inner;\nclass App { void run() { Inner.go(); } }\n",
    })
    assert g.nodes["src.com.y.App.java.App.run"].calls == ["src.com.x.Outer.java.Inner.go"]


def test_go_package_qualified_calls(tmp_path):
    pytest.importorskip("tree_sitter_go")
    g = graph(tmp_path, {
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "money/money.go": "package money\n\nfunc Format(x int) string { return \"\" }\n",
        "report/report.go": "package report\n\nfunc Format(x int) string { return \"\" }\n",
        "cmd/main.go": "package main\n\nimport (\n\t\"fmt\"\n\t\"example.com/shop/money\"\n)\n\n"
                       "func main() { fmt.Println(money.Format(1)) }\n",
    })
    assert g.nodes["cmd.main.go.main"].calls == ["money.money.go.Format"]  # not report.Format, not fmt


def test_java_imported_class_static_calls(tmp_path):
    pytest.importorskip("tree_sitter_java")
    g = graph(tmp_path, {
        "src/main/java/com/shop/Money.java": "package com.shop;\npublic class Money { public static String format(int x) { return \"\"; } }\n",
        "src/main/java/com/report/Report.java": "package com.report;\npublic class Report { public static String format(int x) { return \"\"; } }\n",
        "src/main/java/com/app/App.java": "package com.app;\nimport com.shop.Money;\n"
                                          "class App { void run() { Money.format(1); } }\n",
    })
    assert g.nodes["src.main.java.com.app.App.java.App.run"].calls == ["src.main.java.com.shop.Money.java.Money.format"]


def test_java_standard_library_imports_stay_external_in_maven_layouts(tmp_path):
    pytest.importorskip("tree_sitter_java")
    g = graph(tmp_path, {
        "src/main/java/com/shop/Store.java": "package com.shop;\npublic class Store { public static void add(int x) {} }\n",
        "src/main/java/com/shop/Cart.java": "package com.shop;\nimport java.util.Collections;\n"
                                            "class Cart { void run() { Collections.add(1); } }\n",
    })
    # java.util.Collections is not the project's, even though every path here contains /java/
    assert g.nodes["src.main.java.com.shop.Cart.java.Cart.run"].calls == []
