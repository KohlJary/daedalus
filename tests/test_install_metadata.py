"""T-e27: an install whose metadata lacks what the checkout declares, or that another dist shadows."""

from importlib import metadata

from daedalus import doctor


def test_missing_entry_points_and_deps_are_reported(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('''[project]
name = "daedalus-cli"
version = "0.2.0"
dependencies = [
    "click>=8.0",
    "definitely-not-installed-xyz>=1",
]

[project.entry-points."daedalus.sources"]
github = "daedalus.sources.github:GitHubSource"
brandnew = "daedalus.sources.brandnew:X"
''')

    class FakeDist:
        entry_points = [metadata.EntryPoint("github", "daedalus.sources.github:GitHubSource", "daedalus.sources")]
        version = "0.2.0"

    real = metadata.distribution
    monkeypatch.setattr(metadata, "distribution",
                        lambda name: FakeDist() if name == "daedalus-cli" else real(name))
    monkeypatch.setattr(metadata, "packages_distributions", lambda: {"daedalus": ["daedalus-cli", "daedalus"]})
    names = [f.name for f in doctor.check_install_metadata(tmp_path)]
    msgs = " ".join(f.message for f in doctor.check_install_metadata(tmp_path))
    assert "install-stale" in names and "daedalus.sources:brandnew" in msgs and "definitely-not-installed-xyz" in msgs
    assert "github" not in msgs.split("lacks")[1].split("that")[0]
    assert "install-shadowed" in names and "'daedalus'" in msgs


def test_a_matching_install_reports_nothing(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "daedalus-cli"\ndependencies = [\n    "click>=8.0",\n]\n')

    class FakeDist:
        entry_points = []
        version = "0.2.0"

    real = metadata.distribution
    monkeypatch.setattr(metadata, "distribution", lambda name: FakeDist() if name == "daedalus-cli" else real(name))
    monkeypatch.setattr(metadata, "packages_distributions", lambda: {"daedalus": ["daedalus-cli"]})
    assert doctor.check_install_metadata(tmp_path) == []


def test_markers_and_unusual_toml_are_read(tmp_path):
    import sys

    if sys.version_info < (3, 11):
        return
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'daedalus-cli'\ndependencies = ['click>=8', \"pywin32; sys_platform=='win32'\", "
        "\"tomli; python_version<'3.0'\"]\n[project.entry-points.'daedalus.sources']\nx = 'a:b'\n")
    groups, deps = doctor._declared(tmp_path)
    assert groups == {"daedalus.sources": {"x"}} and "click" in deps
    if sys.platform != "win32":
        assert "pywin32" not in deps and "tomli" not in deps
