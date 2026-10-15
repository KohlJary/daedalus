"""`daedalus oph check` (edict 0017): each lint fires on a broken fixture and not on a clean one."""

from pathlib import Path

from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.ophanic.lint import check_text

ROOT = Path(__file__).resolve().parents[1]

CLEAN = """# Thing

@default
┌──────────┬──────────┐
│ ◆Left    │ ◆Right   │
├──────────┴──────────┤
│ ─ divider (3) ─     │
└─────────────────────┘
note: a note, not content.

## ◆Left
## ◆Right
"""


def kinds(text, path="x.oph", components=None):
    return [p.kind for p in check_text(path, text, components)]


def test_a_clean_diagram_passes():
    assert kinds(CLEAN) == []


def test_ragged_width():
    assert "width" in kinds(CLEAN.replace("│ ◆Left    │", "│ ◆Left   │"))


def test_broken_join():
    assert "joins" in kinds(CLEAN.replace("├──────────┴──────────┤", "├─────────────────────┤"))


def test_mixed_styles():
    assert "style" in kinds(CLEAN.replace("└─────────────────────┘", "╚═════════════════════╝"))


def test_unknown_component_unless_known():
    text = CLEAN.replace("## ◆Right\n", "")
    assert "components" in kinds(text)
    assert kinds(text, components={"Right"}) == []


EDGES = """
┌──────────┐       ┌──────────┐
│ edict 13 │─█E10─▶│ edict 10 │
└──────────┘       └──────────┘
█E10: edict 0013 depends on edict 0010
"""


def test_edge_slugs_need_a_legend_and_legends_need_a_use():
    md = "```oph" + EDGES + "```\n"
    assert kinds(md, "doc.md") == []
    assert "slugs" in kinds(md.replace("█E10: edict 0013 depends on edict 0010\n", ""), "doc.md")
    assert "slugs" in kinds(md.replace("█E10: edict", "█E10: edict").replace("```\n", "█E11: unused\n```\n"), "doc.md")


def test_markdown_outside_oph_fences_is_ignored():
    assert kinds("```\n┌──\n```\n", "doc.md") == []


def test_cli_checks_the_tui_designs_with_its_components():
    out = CliRunner().invoke(main, ["oph", "check", str(ROOT / "docs/design/tui"),
                                    "--components", str(ROOT / "src/daedalus/tui")])
    assert out.exit_code == 0, out.output
