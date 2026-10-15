"""`daedalus oph check` (edict 0017): each lint fires on a broken fixture and not on a clean one."""

from pathlib import Path

import pytest

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


# Momus's trial of the build (2026-10-15): ordinary hand-drawn constructs pass; the broken ones still fail.
HAND_CLEAN = {
    "vertical connector with an arrow": """┌────────┐
│ █E13   │
└───┬────┘
    │
    ▼
┌────────┐
│ █E10   │
└────────┘
█E13: edict 13
█E10: edict 10
""",
    "vertical connector into a junction": """┌────────┐
│ A      │
└───┬────┘
    │
┌───┴────┐
│ B      │
└────────┘
""",
    "arrow pointing up": """┌────────┐
│ A      │
└───┬────┘
    ▲
    │
┌───┴────┐
│ B      │
└────────┘
""",
    "title in the top border": """┌─ Title ────┐
│ body       │
└────────────┘
""",
    "title with two words in a rounded border": """╭─ Two words ──╮
│ body         │
╰──────────────╯
""",
    "dropdown caret in a field": """┌──────────────┐
│ Sort by  ▼   │
└──────────────┘
""",
    "disclosure triangles": """┌──────────────┐
│ ▶ Section    │
│ ▼ Open       │
│   child      │
└──────────────┘
""",
    "light dashed edge": """┌──────┐      ┌──────┐
│ A    │┄┄┄┄┄▶│ B    │
└──────┘      └──────┘
""",
    "dashed edge with ╌": """┌──────┐      ┌──────┐
│ A    │╌╌╌╌╌▶│ B    │
└──────┘      └──────┘
""",
    "edge pointing left": """┌──────┐      ┌──────┐
│ A    │◀─────│ B    │
└──────┘      └──────┘
""",
    "labels to the left of a box": """Header ┌──────┐
       │ A    │
Body   │ B    │
       └──────┘
""",
    "side-attached edge with a slug": """┌──────────┐       ┌──────────┐
│ █E13     │─█R11─▶│ █E10     │
└──────────┘       └──────────┘
█E13: edict 13
█E10: edict 10
█R11: depends on
""",
}

HAND_BROKEN = {
    "missing wall": """┌──────┐
│ A
└──────┘
""",
    "shifted wall": """┌──────┐
│ A     │
└──────┘
""",
    "no bottom": """┌──────┐
│ A    │
""",
    "no sides": """┌──────┐
  A
└──────┘
""",
    "short top": """┌────┐
│ A    │
└──────┘
""",
    "orphan ┬": """┌───┬──┐
│ A    │
└──────┘
""",
    "orphan ┴": """┌──────┐
│ A    │
└──┴───┘
""",
    "mixed styles": """┌──────┐
│ A    │
└──────┘
╔══════╗
║ B    ║
╚══════╝
""",
    "ragged widths": """┌──────┐
│ A    │
│ B     │
└──────┘
""",
    "missing component": """┌──────┐
│ ◆Nope│
└──────┘
""",
    "title, border too long": """┌─ Title ─────┐
│ body         │
└──────────────┘
""",
    "arrow dangling in space": """┌──────┐
│ A    │───▶
└──────┘
""",
    "edge ending at nothing": """┌──────┐
│ A    │──────
└──────┘
""",
    "connector that stops short": """┌────────┐
│ A      │
└───┬────┘
    │

""",
    "vertical arrow pointing at nothing": """┌────────┐
│ A      │
└───┬────┘
    ▼

""",
}


@pytest.mark.parametrize("name", sorted(HAND_CLEAN))
def test_hand_drawn_constructs_pass(name):
    assert check_text("t.oph", "# T\n\n@x\n" + HAND_CLEAN[name]) == [], name


@pytest.mark.parametrize("name", sorted(HAND_BROKEN))
def test_broken_diagrams_fail(name):
    assert check_text("t.oph", "# T\n\n@x\n" + HAND_BROKEN[name]) != [], name


def test_hand_drawn_flow_in_markdown_passes():
    md = "```oph\n" + HAND_CLEAN["vertical connector with an arrow"] + "```\n"
    assert check_text("doc.md", md) == []


def test_docs_ophanic_passes_its_own_lint():
    assert check_text("docs/ophanic.md", (ROOT / "docs/ophanic.md").read_text(encoding="utf-8")) == []


def test_stacked_boxes_of_different_widths_under_a_connector_pass():
    flow = """┌──────────┐      ┌──────────┐
│ A        │─────▶│ B        │
└────┬─────┘      └──────────┘
     │
     ▼
┌──────────┐
│ C        │
└──────────┘
"""
    assert check_text("t.oph", "@x\n" + flow) == []
    ragged = flow.replace("│ B        │", "│ B         │")
    assert "width" in [p.kind for p in check_text("t.oph", "@x\n" + ragged)]


def test_an_oph_fence_glued_to_its_last_line_is_reported():
    md = "```oph\n┌──┐\n│  │\n└──┘```\n\nMore prose.\n"
    assert "fence" in kinds(md, "doc.md")
    assert kinds(md.replace("└──┘```", "└──┘\n```"), "doc.md") == []
