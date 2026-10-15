"""
`daedalus oph check`: a deterministic lint for Ophanic diagrams as drawn (edict 0017).

A diagram is a run of consecutive lines that start with a box-drawing character. It is found:
- in an `.oph` file, under an `@variant` line;
- in Markdown, inside a fenced ```oph block.

Lines after a diagram that start with `note:`, or with a slug and a colon (`█E07: ...`), are its notes and
legend; they are not content.

What it checks, each with a line number:
- **width:** every row of a diagram has the same display width;
- **joins:** every box character's arms meet a neighbour with the matching arm (a `┬` needs something below
  it, a `─` needs something on both sides, and so on). Arrows end an edge, and a slug inside an edge
  (`─█R11─▶`) is part of the line;
- **style:** one box style per diagram (light/rounded, heavy, or double, not mixed);
- **components:** every `◆Name` has a `## ◆Name` section in the same file, or is a known component
  (`--components`);
- **slugs:** every slug on an edge has a legend line, and every legend line is used.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

U, D, L, R = "U", "D", "L", "R"
ARMS = {
    "─": {L, R}, "│": {U, D}, "┌": {R, D}, "┐": {L, D}, "└": {R, U}, "┘": {L, U},
    "├": {U, D, R}, "┤": {U, D, L}, "┬": {L, R, D}, "┴": {L, R, U}, "┼": {U, D, L, R},
    "╭": {R, D}, "╮": {L, D}, "╰": {R, U}, "╯": {L, U},
    "━": {L, R}, "┃": {U, D}, "┏": {R, D}, "┓": {L, D}, "┗": {R, U}, "┛": {L, U},
    "┣": {U, D, R}, "┫": {U, D, L}, "┳": {L, R, D}, "┻": {L, R, U}, "╋": {U, D, L, R},
    "═": {L, R}, "║": {U, D}, "╔": {R, D}, "╗": {L, D}, "╚": {R, U}, "╝": {L, U},
    "╠": {U, D, R}, "╣": {U, D, L}, "╦": {L, R, D}, "╩": {L, R, U}, "╬": {U, D, L, R},
    # Arrows end an edge: they only need the line coming into them
    "▶": {L}, "◀": {R}, "▼": {U}, "▲": {D},
}
STYLE = {**{c: "light" for c in "─│┌┐└┘├┤┬┴┼╭╮╰╯"}, **{c: "heavy" for c in "━┃┏┓┗┛┣┫┳┻╋"},
         **{c: "double" for c in "═║╔╗╚╝╠╣╦╩╬"}}
BOX_START = set("┌└├│╭╰┏┗┣┃╔╚╠║")
OPPOSITE = {U: D, D: U, L: R, R: L}
HORIZONTAL = set("─━═")
MAX_WIDTH = 100
# An edge written inside a box ("─▶ █E10 █E11") is text for joining purposes, as are listed edges
EDGE_TOKEN = re.compile(r"(?<![─━═┌└├┬┴┼│])─+▶(?=\s)")
VERTICAL = set("│┃║├┤┣┫╠╣")
STEP = {U: (-1, 0), D: (1, 0), L: (0, -1), R: (0, 1)}
SLUG = re.compile(r"█[A-Z]\d{1,4}")
LEGEND = re.compile(r"^\s*(█[A-Z]\d{1,4})\s*:")
LISTED = re.compile(r"^\s*(█[A-Z]\d{1,4}) ─▶ (█[A-Z]\d{1,4})")
COMPONENT = re.compile(r"◆([A-Z][A-Za-z0-9]*)")


@dataclass
class Problem:
    path: str
    line: int
    kind: str
    message: str


@dataclass
class Diagram:
    start: int          # 1-based line number of its first row
    rows: list[str]
    after: list[str]    # notes and legend lines that follow it


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 0 if unicodedata.combining(ch) else 1
               for ch in text)


def _is_row(line: str) -> bool:
    s = line.lstrip()
    return bool(s) and s[0] in BOX_START


def diagrams(text: str, markdown: bool = False) -> list[Diagram]:
    lines = text.splitlines()
    out: list[Diagram] = []
    inside = not markdown
    i = 0
    while i < len(lines):
        line = lines[i]
        if markdown and line.strip().startswith("```"):
            inside = line.strip() in ("```oph", "```ophanic") if not inside else False
            i += 1
            continue
        if inside and _is_row(line):
            start = i
            while i < len(lines) and _is_row(lines[i]):
                i += 1
            after = []
            j = i
            while j < len(lines) and (lines[j].startswith("note:") or LEGEND.match(lines[j]) or LISTED.match(lines[j])
                                      or (lines[j].startswith(" ") and after and lines[j].strip())):
                after.append(lines[j])
                j += 1
            out.append(Diagram(start + 1, lines[start:i], after))
            continue
        i += 1
    return out


def _cells(rows: list[str]) -> list[list[str]]:
    rows = [EDGE_TOKEN.sub(lambda m: " " * len(m.group(0)), r) for r in rows]
    grid = [list(r) for r in rows]
    # A slug inside an edge (─█R11─▶) is part of the line: treat its characters as ─ for joining
    for r, row in enumerate(rows):
        for m in SLUG.finditer(row):
            a, b = m.start(), m.end()
            left = row[a - 1] if a > 0 else ""
            right = row[b] if b < len(row) else ""
            if left in ARMS and R in ARMS[left] and right in ARMS and L in ARMS[right]:
                for c in range(a, b):
                    grid[r][c] = "─"
    return grid


def check_diagram(path: str, d: Diagram, components: set[str], sections: set[str]) -> list[Problem]:
    out: list[Problem] = []
    widths = {width(r.rstrip()) for r in d.rows}
    if max(widths, default=0) > MAX_WIDTH:
        out.append(Problem(path, d.start, "width", f"the diagram is {max(widths)} wide; at most {MAX_WIDTH}"))
    if len(widths) > 1:
        common = max(widths, key=lambda w: sum(1 for r in d.rows if width(r.rstrip()) == w))
        for k, r in enumerate(d.rows):
            if width(r.rstrip()) != common:
                out.append(Problem(path, d.start + k, "width",
                                   f"row is {width(r.rstrip())} wide, the diagram is {common}"))
    grid = _cells([r.rstrip() for r in d.rows])

    def at(r, c):
        return grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else " "
    styles = {STYLE[ch] for row in grid for ch in row if ch in STYLE}
    if len(styles - {"light"}) + (1 if "light" in styles else 0) > 1:
        out.append(Problem(path, d.start, "style", f"mixed box styles in one diagram: {', '.join(sorted(styles))}"))

    # A run of horizontal line characters that joins nothing at either end is text ("─ done (10) ─"), not box
    decorative: set[tuple[int, int]] = set()
    for r, row in enumerate(grid):
        c = 0
        while c < len(row):
            if row[c] in HORIZONTAL:
                a = c
                while c < len(row) and row[c] in HORIZONTAL:
                    c += 1
                left_joins = R in ARMS.get(at(r, a - 1), set())
                right_joins = L in ARMS.get(at(r, c), set())
                if not left_joins and not right_joins:
                    decorative |= {(r, k) for k in range(a, c)}
            else:
                c += 1

    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            arms = ARMS.get(ch)
            if not arms or (r, c) in decorative:
                continue
            for arm in arms:
                dr, dc = STEP[arm]
                other = at(r + dr, c + dc)
                # An edge may attach to a box's side: a horizontal line or arrow meeting a vertical edge
                attaches = arm in (L, R) and (ch in HORIZONTAL or ch in "▶◀") and other in VERTICAL
                if not attaches and OPPOSITE[arm] not in ARMS.get(other, set()):
                    out.append(Problem(path, d.start + r, "joins",
                                       f"'{ch}' at column {c + 1} has nothing to join {dict(U='above', D='below', L='on its left', R='on its right')[arm]}"))
                    break
    text = "\n".join(d.rows)
    for name in sorted(set(COMPONENT.findall(text))):
        if name not in sections and name not in components:
            out.append(Problem(path, d.start, "components", f"◆{name} has no ## ◆{name} section and isn't a known component"))
    used = set(SLUG.findall(text)) | {s for line in d.after if (m := LISTED.match(line)) for s in m.groups()}
    legend = {m.group(1) for line in d.after if (m := LEGEND.match(line))}
    for s in sorted(used - legend):
        out.append(Problem(path, d.start, "slugs", f"{s} is used in the diagram but has no legend line"))
    for s in sorted(legend - used):
        out.append(Problem(path, d.start, "slugs", f"legend line {s} isn't used in the diagram"))
    return out


def definitions(text: str) -> set[str]:
    """What an .oph file defines: its `## ◆Name` sections, and its title when it draws a screen."""
    names = set(re.findall(r"^## ◆([A-Z][A-Za-z0-9]*)", text, re.M))
    lines = text.splitlines()
    top = text.split("\n## ", 1)[0]
    if lines and lines[0].startswith("# ") and re.search(r"^@[a-z]", top, re.M):
        names.add(lines[0][2:].strip())
    return names


def check_text(path: str, text: str, components: Optional[set[str]] = None,
               siblings: Optional[set[str]] = None, strict: bool = False) -> list[Problem]:
    markdown = path.endswith(".md")
    sections = set() if strict else definitions(text) | (siblings or set())
    out: list[Problem] = []
    for d in diagrams(text, markdown=markdown):
        out += check_diagram(path, d, components or set(), sections)
    return out


def components_from_package(package_dir: Path) -> set[str]:
    """Class names defined under a package directory: the widgets a ◆ may refer to."""
    found: set[str] = set()
    for f in Path(package_dir).rglob("*.py"):
        found |= set(re.findall(r"^class (\w+)\(", f.read_text(encoding="utf-8"), re.M))
    return found


def check_paths(paths: Iterable[Path], components: Optional[set[str]] = None, strict: bool = False) -> list[Problem]:
    """Lint every .oph file and ```oph block under the paths. With `strict`, every ◆Name must be a known component
    (a class), not just a section: how the TUI checks that each drawn component exists in code (edict 0012)."""
    out: list[Problem] = []
    known = set(components or set())
    known |= {n[:-len("Screen")] for n in known if n.endswith("Screen")}
    for p in paths:
        p = Path(p)
        files = sorted(p.rglob("*.oph")) + sorted(p.rglob("*.md")) if p.is_dir() else [p]
        sibling_defs: dict[Path, set[str]] = {}
        for f in files:
            if f.parent not in sibling_defs:
                sibling_defs[f.parent] = set()
                for g in f.parent.glob("*.oph"):
                    try:
                        sibling_defs[f.parent] |= definitions(g.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError):
                        pass
        for f in files:
            try:
                out += check_text(str(f), f.read_text(encoding="utf-8"), known,
                                  set() if strict else sibling_defs[f.parent], strict=strict)
            except (OSError, UnicodeDecodeError) as e:
                out.append(Problem(str(f), 0, "read", str(e)))
    return out
