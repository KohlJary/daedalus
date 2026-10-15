"""Every ◆Name in docs/design/tui/*.oph has a widget class of that name in daedalus.tui (edict 0012).

Run: python scripts/check_oph_widgets.py   (exit 1 and a list when any is missing)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def components() -> set[str]:
    names = set()
    for f in (ROOT / "docs" / "design" / "tui").glob("*.oph"):
        names |= set(re.findall(r"◆([A-Z][A-Za-z]+)", f.read_text(encoding="utf-8")))
        text = f.read_text(encoding="utf-8")
        title = text.splitlines()[0]
        top = text.split("\n## ", 1)[0]
        # The file's title is a screen only when the file draws one at the top level (an @variant there)
        if title.startswith("# ") and re.search(r"^@[a-z]", top, re.M):
            names.add(title[2:].strip())
    return names


def classes() -> set[str]:
    found = set()
    for f in (ROOT / "src" / "daedalus" / "tui").rglob("*.py"):
        found |= set(re.findall(r"^class (\w+)\(", f.read_text(encoding="utf-8"), re.M))
    return found


def missing() -> list[str]:
    have = classes()
    # A screen file's title (e.g. "# Board") is satisfied by BoardScreen as well as Board
    return sorted(n for n in components() if n not in have and f"{n}Screen" not in have)


if __name__ == "__main__":
    gaps = missing()
    for g in gaps:
        print(f"missing widget class: {g}")
    sys.exit(1 if gaps else 0)
