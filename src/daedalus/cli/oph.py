"""`daedalus oph`: Ophanic, Daedalus's spatial language (edict 0017)."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group("oph")
def oph():
    """Ophanic diagrams: lint them (check) and draw Daedalus's own state (map)."""


def project_root(start: Path) -> Path:
    """The nearest directory at or above `start` that holds `.daedalus`, else `start`: maps read the project, not
    whatever directory the command ran in."""
    for d in [start, *start.parents]:
        if (d / ".daedalus").is_dir():
            return d
    return start


@oph.command("check")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
@click.option("--components", default=None,
              help="Known components: a comma list, or a package directory whose classes count (e.g. src/daedalus/tui)")
@click.option("--strict-components", is_flag=True, help="Every ◆Name must be a known component, not just a section")
@click.option("--json", "as_json", is_flag=True)
def oph_check(paths, components, strict_components, as_json):
    """Lint .oph files and ```oph blocks in Markdown: widths, joins, box style, ◆ components, slugs and legends."""
    from ..ophanic.lint import check_paths, components_from_package

    known: set[str] = set()
    if components:
        p = Path(components)
        known = components_from_package(p) if p.is_dir() else {c.strip() for c in components.split(",") if c.strip()}
    targets = [Path(p) for p in paths] or [Path("docs/design")]
    problems = check_paths([t for t in targets if t.exists()], known, strict=strict_components)
    if as_json:
        from ..ophanic.render import read_diagram_edges

        # Per file, per diagram: the same slugs in two @variants are separate diagrams, not one graph
        edges = {}
        for t in targets:
            files = [t] if t.is_file() else sorted(t.rglob("*.oph")) + sorted(t.rglob("*.md"))
            for f in files:
                try:
                    found = read_diagram_edges(f.read_text(encoding="utf-8"), markdown=f.suffix == ".md")
                except (OSError, UnicodeDecodeError):
                    continue
                if found or f.suffix == ".oph":
                    edges[str(f)] = found
        click.echo(json.dumps({"problems": [p.__dict__ for p in problems], "edges": edges}, indent=2, ensure_ascii=False))
    else:
        for p in problems:
            click.echo(f"{p.path}:{p.line}: {p.kind}: {p.message}")
        if not problems:
            click.echo("No problems found.")
    raise SystemExit(1 if problems else 0)


@oph.command("map")
@click.argument("subject", type=click.Choice(["edicts", "plan", "workstreams", "intake"]))
@click.option("--width", type=click.Choice(["100", "60", "34"]), default="100")
@click.option("--workstream", "-w", default=None, help="plan: this workstream's plan")
@click.option("--json", "as_json", is_flag=True, help="The graph the diagram was drawn from, edges marked drawn/listed")
def oph_map(subject, width, workstream, as_json):
    """Draw Daedalus's own state as an Ophanic diagram: edicts and their dependencies, the plan, workstreams
    and their claims, or intake (sources to roadmap to phases)."""
    from ..ophanic.maps import MAPS
    from ..ophanic.render import draw

    root = project_root(Path.cwd())
    graph = MAPS[subject](root, workstream) if subject == "plan" else MAPS[subject](root)
    text, data = draw(graph, int(width))
    click.echo(json.dumps(data, indent=2, ensure_ascii=False) if as_json else text, nl=not as_json or True)


@oph.command("draw")
@click.argument("graph_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--width", type=click.Choice(["100", "60", "34"]), default="100")
@click.option("--json", "as_json", is_flag=True)
def oph_draw(graph_file, width, as_json):
    """Draw any graph as an Ophanic diagram. GRAPH_FILE is JSON:
    {"title", "nodes": [{"id", "label", "kind", "mark"?, "parent"?, "detail"?}], "edges": [{"from", "to", "label"?}]}.
    kind is one letter (E edict, P phase, T task, R roadmap item, W workstream, S source, M module, C claim, N other)."""
    from ..ophanic.render import GraphError, draw

    try:
        graph = json.loads(Path(graph_file).read_text(encoding="utf-8"))
        text, data = draw(graph, int(width))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise click.ClickException(f"{graph_file} is not valid JSON: {e}")
    except GraphError as e:
        raise click.ClickException(f"{graph_file}: {e}")
    click.echo(json.dumps(data, indent=2, ensure_ascii=False) if as_json else text)
