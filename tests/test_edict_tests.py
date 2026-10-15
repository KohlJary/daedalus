"""Edicts with tests attached (dream pick 38): criteria -> skipped tests -> doctor hint."""

import subprocess

from click.testing import CliRunner

from daedalus import edict_tests as et
from daedalus.cli.main import main
from daedalus.doctor import load_edicts, edict_test_hints

EDICT = """# Edict 0042: Widgets
Status: accepted

## Intent
Make widgets.

## Acceptance criteria
- `daedalus widget list` prints every widget.
  It includes hidden ones with --all.
- [AC-export] Widgets export to JSON.
- Importing **twice** changes nothing.

## Non-goals
- No gadgets.
"""


def project(tmp_path):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0042-widgets.md").write_text(EDICT)
    return tmp_path


def test_criteria_have_stable_ids_and_keep_their_sub_lines(tmp_path):
    crits = et.edict_criteria(project(tmp_path), "42")
    assert [c.id for c in crits] == ["daedalus_widget_list_prints_every_widget", "ac_export",
                                     "importing_twice_changes_nothing"]
    assert "hidden ones with --all" in crits[0].text and not crits[1].text.startswith("[")


def test_write_adds_skipped_tests_never_overwrites_and_status_tracks_them(tmp_path, monkeypatch):
    repo = project(tmp_path)
    path, added = et.write_skeleton(repo, "0042")
    assert len(added) == 3 and path.name == "test_edict_0042.py"
    assert set(et.status(repo, "0042").values()) == {"skeleton"}
    # The builder replaces one skip with a real test
    text = path.read_text().replace(
        '@pytest.mark.skip(reason=\'criterion not yet tested\')\ndef test_0042_ac_export():',
        'def test_0042_ac_export():')
    path.write_text(text)
    assert et.status(repo, "0042")["ac_export"] == "tested"
    _, again = et.write_skeleton(repo, "0042")
    assert again == [] and path.read_text() == text
    # The generated file is valid and its skeletons are skipped by pytest
    out = subprocess.run(["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", str(path)], capture_output=True,
                         text=True, cwd=repo)
    assert "2 skipped" in out.stdout and "1 passed" in out.stdout, out.stdout


def test_cli_and_doctor_hint(tmp_path, monkeypatch):
    repo = project(tmp_path)
    monkeypatch.chdir(repo)
    out = CliRunner().invoke(main, ["edict", "tests", "42", "--write"])
    assert out.exit_code == 0 and "0 tested, 3 skeleton" in out.output
    hints = edict_test_hints(repo, load_edicts(repo))
    assert hints and "3 of 3 acceptance criteria" in hints[0]
