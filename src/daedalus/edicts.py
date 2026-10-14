"""
Edicts and dissents (edicts 0001, 0003, 0005).

An edict is a human-approved design: `docs/edicts/NNNN-slug.md` with a `Status:` line and `## `
sections. Its Intent and Acceptance criteria are the approved intent that Ariadne's judge grades
diffs against (0001). A dissent is an agent's recorded objection to an edict
(`docs/edicts/dissents/NNNN-<agent>.md`); while one is open, the edict is not dispatched and its
diffs are not auto-approved (0003).

Parsing stays deliberately shallow (0001's non-goal): the `Status:` line and the `## ` headings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from .config import edicts_setting

EDICT_FILE = re.compile(r"^(\d{4})-.+\.md$")
STATUS_LINE = re.compile(r"^Status:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
SECTION = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
DISSENT_FILE = re.compile(r"^(\d{4})-([\w.-]+?)(?:-(\d+))?\.md$")
OUTCOMES = ("amended", "overruled", "withdrawn")
INTENT_SECTIONS = ("Intent", "Acceptance criteria")


class EdictError(Exception):
    """An edict or dissent operation that can't proceed."""


@dataclass
class Edict:
    number: str
    path: Path
    status: str
    title: str
    text: str
    sections: dict = field(default_factory=dict)


@dataclass
class Dissent:
    path: Path
    edict: str
    agent: str
    status: str  # open | resolved
    filed: str
    outcome: Optional[str] = None


def edicts_dir(repo: Path) -> Path:
    return Path(repo) / "docs" / "edicts"


RESOLVE_PERMISSION = "Bash(daedalus edict resolve-dissent:*)"


def dissents_dir(repo: Path) -> Path:
    return edicts_dir(repo) / "dissents"


def _parse(path: Path, number: str) -> Edict:
    text = path.read_text(encoding="utf-8")
    status = STATUS_LINE.search(text)
    title = next((l[2:].split(":", 1)[-1].strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
    heads = list(SECTION.finditer(text))
    sections = {
        m.group(1): text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        for i, m in enumerate(heads)
    }
    return Edict(number, path, (status.group(1) if status else "").lower(), title, text, sections)


def load_edict(repo: Path, number: str) -> Edict:
    """The edict with this number. Raises EdictError if it is missing or the number is ambiguous."""
    number = str(number).zfill(4)
    folder = edicts_dir(repo)
    matches = sorted(p for p in folder.glob("*.md") if (m := EDICT_FILE.match(p.name)) and m.group(1) == number) \
        if folder.is_dir() else []
    if not matches:
        raise EdictError(f"No edict {number} in {folder}")
    if len(matches) > 1:
        raise EdictError(f"Edict {number} is ambiguous: {', '.join(p.name for p in matches)}")
    return _parse(matches[0], number)


def approved_intent(edict: Edict) -> str:
    """The approved intent the judge grades against: the edict's Intent and Acceptance criteria."""
    parts = [f"Edict {edict.number}: {edict.title}"]
    for name in INTENT_SECTIONS:
        if edict.sections.get(name):
            parts.append(f"## {name}\n{edict.sections[name]}")
    return "\n\n".join(parts)


# ---------- dissents ----------


def _parse_dissent(path: Path) -> Optional[Dissent]:
    m = DISSENT_FILE.match(path.name)
    if not m:
        return None
    text = path.read_text(encoding="utf-8")

    def field_of(name: str) -> Optional[str]:
        found = re.search(rf"^{name}:\s*(.*?)\s*$", text, re.MULTILINE)
        return found.group(1) if found else None

    return Dissent(path, m.group(1), field_of("Agent") or m.group(2), (field_of("Status") or "open").lower(),
                   field_of("Filed") or "", field_of("Outcome"))


def list_dissents(repo: Path, open_only: bool = True) -> list[Dissent]:
    folder = dissents_dir(repo)
    if not folder.is_dir():
        return []
    def order(p: Path):
        m = DISSENT_FILE.match(p.name)
        return (m.group(1), m.group(2), int(m.group(3) or 1)) if m else (p.name, "", 0)

    found = [d for p in sorted(folder.glob("*.md"), key=order) if (d := _parse_dissent(p))]
    return [d for d in found if d.status == "open"] if open_only else found


def open_dissents_for(repo: Path, number: str) -> list[Dissent]:
    number = str(number).zfill(4)
    return [d for d in list_dissents(repo) if d.edict == number]


def file_dissent(repo: Path, number: str, agent: str, objection: str, why: str, instead: str) -> Path:
    """Record a dissent. Never touches the edict itself."""
    edict = load_edict(repo, number)
    for name, value in (("objection", objection), ("why", why), ("instead", instead)):
        if not value.strip():
            raise EdictError(f"A dissent states what it objects to, why, and what it would do instead ({name} is empty)")
    slug = re.sub(r"[^\w.-]+", "-", agent.strip().lower()) or "agent"
    folder = dissents_dir(repo)
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{edict.number}-{slug}.md", 2
    while path.exists():
        path, n = folder / f"{edict.number}-{slug}-{n}.md", n + 1
    path.write_text(
        f"# Dissent on edict {edict.number}: {edict.title}\n"
        f"Status: open\nEdict: {edict.number}\nAgent: {agent}\nFiled: {date.today().isoformat()}\n\n"
        f"## Objection\n{objection.strip()}\n\n## Why\n{why.strip()}\n\n## Instead\n{instead.strip()}\n",
        encoding="utf-8",
    )
    return path


def resolve_dissent(repo: Path, name: str, outcome: str, note: str) -> Path:
    """Mark a dissent resolved, appending the outcome. The dissent's history stays in the file."""
    if outcome not in OUTCOMES:
        raise EdictError(f"Outcome must be one of {', '.join(OUTCOMES)}")
    folder = dissents_dir(repo)
    filename = name if name.endswith(".md") else f"{name}.md"
    if "/" in filename or "\\" in filename or not DISSENT_FILE.match(filename):
        raise EdictError(f"'{name}' is not a dissent name (expected NNNN-agent, as listed by `edict dissents`)")
    path = folder / filename
    if not path.exists():
        raise EdictError(f"No dissent {path.name} in {folder}")
    dissent = _parse_dissent(path)
    if dissent is None or dissent.status != "open":
        raise EdictError(f"{path.name} is not an open dissent")
    text = path.read_text(encoding="utf-8")
    text = STATUS_LINE.sub("Status: resolved", text, count=1)
    text = text.rstrip("\n") + (
        f"\n\n## Resolution\nResolved: {date.today().isoformat()}\nOutcome: {outcome}\n\n{note.strip()}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


# ---------- gates ----------


def dispatch_block(repo: Path, number: str) -> Optional[str]:
    """Why work on this edict may not be dispatched now, or None if it may."""
    try:
        edict = load_edict(repo, number)
    except EdictError as e:
        return str(e)
    if edict.status != "accepted":
        return f"Edict {edict.number} has Status: {edict.status or '(none)'}; only accepted edicts are dispatched"
    dissents = open_dissents_for(repo, edict.number)
    if dissents:
        return f"Edict {edict.number} has an open dissent ({', '.join(d.path.name for d in dissents)}); work is paused"
    return None


def intent_block(edict: Edict) -> Optional[str]:
    """Why an edict can't serve as approved intent, or None: it needs a non-empty Intent section."""
    if not edict.sections.get("Intent"):
        return f"Edict {edict.number} has no Intent section to grade against"
    return None


def intent_for_diff(repo: Path, metadata: dict) -> tuple[Optional[str], str]:
    """
    (approved intent, reason) for a diff. The intent comes from the edict file in the checkout,
    never from the diff (whose metadata a worker could influence). None means no approved intent:
    the diff isn't tied to an edict, edicts are off, or the edict isn't accepted or has an open
    dissent. The reason says which.
    """
    number = metadata.get("edict")
    if not number:
        return None, "No approved intent: the diff is not tied to an edict, so a human reviews it."
    if not edicts_setting(Path(repo))[0]:
        return None, "No approved intent: edicts are off in this project, so a human reviews every diff."
    block = dispatch_block(repo, str(number))
    if block:
        return None, f"No approved intent: {block}."
    edict = load_edict(repo, str(number))
    block = intent_block(edict)
    if block:
        return None, f"No approved intent: {block}."
    return approved_intent(edict), ""


def mark_done(repo: Path, number: str) -> Path:
    """Move an accepted edict to done (the one status change Daedalus makes)."""
    edict = load_edict(repo, number)
    if edict.status != "accepted":
        raise EdictError(f"Edict {edict.number} is {edict.status or '(no status)'}, not accepted")
    edict.path.write_text(STATUS_LINE.sub("Status: done", edict.text, count=1), encoding="utf-8")
    return edict.path
