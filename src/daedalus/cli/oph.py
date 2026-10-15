"""`daedalus oph`: Ophanic, Daedalus's spatial language (edict 0016)."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group("oph")
def oph():
    """Ophanic diagrams: lint them (check) and draw Daedalus's own state (map)."""


@oph.command("check")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--components", default=None,
              help="Known components: a comma list, or a package directory whose classes count (e.g. src/daedalus/tui)")
@click.option("--json", "as_json", is_flag=True)
def oph_check(paths, components, as_json):
    """Lint .oph files and ```oph blocks in Markdown: widths, joins, box style, ◆ components, slugs and legends."""
    from ..ophanic.lint import check_paths, components_from_package

    known: set[str] = set()
    if components:
        p = Path(components)
        known = components_from_package(p) if p.is_dir() else {c.strip() for c in components.split(",") if c.strip()}
    targets = [Path(p) for p in paths] or [Path("docs/design")]
    problems = check_paths([t for t in targets if t.exists()], known)
    if as_json:
        click.echo(json.dumps([p.__dict__ for p in problems], indent=2))
    else:
        for p in problems:
            click.echo(f"{p.path}:{p.line}: {p.kind}: {p.message}")
        if not problems:
            click.echo("No problems found.")
    raise SystemExit(1 if problems else 0)
