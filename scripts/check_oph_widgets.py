"""Every ◆Name in docs/design/tui/*.oph has a widget class of that name in daedalus.tui (edict 0012), checked by
`daedalus oph check --strict-components` (edict 0017). Kept so the TUI's test and old instructions still work.

Run: python scripts/check_oph_widgets.py   (exit 1 and a list when any is missing)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def missing() -> list[str]:
    from daedalus.ophanic.lint import check_paths, components_from_package

    problems = check_paths([ROOT / "docs" / "design" / "tui"], components_from_package(ROOT / "src" / "daedalus" / "tui"),
                           strict=True)
    names = set()
    for p in problems:
        if p.kind == "components":
            names.add(p.message.split()[0].lstrip("◆"))
    return sorted(names)


if __name__ == "__main__":
    gaps = missing()
    for g in gaps:
        print(f"missing widget class: {g}")
    sys.exit(1 if gaps else 0)
