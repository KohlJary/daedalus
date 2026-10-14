"""
Deterministic checks on a reflection report (edict 0010), before Momus or the user sees it.

A report is JSON written by the `delphi` agent (REPORT_SCHEMA): findings, proposals, and at the
monthly level the evolution, lineage and aspiration sections. The check confirms that:

- every finding and proposal cites evidence as `[s:<session-id> e:<event-uuid>]` or
  `[s:<session-id> d:<digest-field>]`, and every citation resolves to a digest;
- a finding of a counted type cites only events of that type (a failed-tool-call finding cites
  failures), and every figure matches the digest field it cites;
- proposals respect the model rules: scope, what the user model may hold, self entry kinds,
  stances, affirmations, tombstones;
- a monthly report carries the sections the bundle requires.

It cannot tell whether a citation supports what the finding says. That is Momus's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import models as m
from .digest import load_digests
from .paths import claude_dir

REPORT_SCHEMA = "daedalus.reflection-report/1"
LEVELS = ("daily", "weekly", "monthly")
CITATION = re.compile(r"\[s:([A-Za-z0-9_-]+) ([ed]):([^\]\s]+)\]")
CITATION_START = re.compile(r"\[s:")
FINDING_TYPES = {
    "failed_tool_call": "failures", "retry": "retries", "re_read": "re_reads",
    "denied_by_classifier": "denied_by_classifier", "rejected_by_user": "rejected_by_user",
    "interruption": "interruptions", "interruption_before_reply": "interruptions_before_reply",
    "tokens": None, "subagents": None, "pattern": None, "other": None,
}
TARGETS = ("model", "file", "permission", "gameplan")
FILE_OPS = ("append", "replace")
GAMEPLAN_KINDS = ("task-status", "new-task")


@dataclass
class CheckResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    findings: int = 0
    proposals: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def citations(text: str) -> tuple[list[tuple[str, str, str]], int]:
    """(session, kind, ref) for each well-formed citation, and how many `[s:` starts were malformed."""
    good = CITATION.findall(text or "")
    starts = len(CITATION_START.findall(text or ""))
    return good, starts - len(good)


def field_value(digest: dict, dotted: str) -> Any:
    node: Any = digest
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise KeyError(dotted)
    return node


def _event_uuids(digest: dict) -> set[str]:
    uuids = {u for us in (digest.get("events") or {}).values() for u in us if u}
    for c in digest.get("calls") or []:
        uuids.update(u for u in (c.get("uuid"), c.get("result")) if u)
    return uuids


def check_report(project_dir: Path, report: dict, models_root: Optional[Path] = None,
                 bundle: Optional[dict] = None, scope: str = "work") -> CheckResult:
    result = CheckResult()
    err = result.errors.append
    if report.get("schema") != REPORT_SCHEMA:
        err(f"schema must be {REPORT_SCHEMA}")
    level = report.get("level")
    if level not in LEVELS:
        err(f"level must be one of {LEVELS}")
    digests = {d["session_id"]: d for d in load_digests(project_dir)}

    def check_citations(where: str, text: str, require: bool = True) -> list[tuple[str, str, str]]:
        found, malformed = citations(text)
        if malformed:
            err(f"{where}: {malformed} citation(s) not in the form [s:<session> e:<uuid>] or [s:<session> d:<field>]")
        if require and not found:
            err(f"{where}: no citation")
        for session, kind, ref in found:
            digest = digests.get(session)
            if digest is None:
                err(f"{where}: cites session {session}, which has no digest")
            elif kind == "e" and ref not in _event_uuids(digest):
                err(f"{where}: cites event {ref}, which is not in session {session}'s digest")
            elif kind == "d":
                try:
                    field_value(digest, ref)
                except KeyError:
                    err(f"{where}: cites digest field {ref}, which session {session}'s digest doesn't have")
        return found

    for i, f in enumerate(report.get("findings") or []):
        result.findings += 1
        where = f"finding {f.get('id') or i + 1}"
        ftype = f.get("type")
        if ftype not in FINDING_TYPES:
            err(f"{where}: type must be one of {sorted(FINDING_TYPES)}")
        found = check_citations(where, f.get("text", ""))
        counter = FINDING_TYPES.get(ftype)
        if counter:
            for session, kind, ref in found:
                if kind == "e" and session in digests and ref not in (digests[session].get("events") or {}).get(counter, []):
                    err(f"{where}: a {ftype} finding cites event {ref}, which is not one of session {session}'s {counter}")
        for fig in f.get("figures") or []:
            cites, _ = citations(fig.get("cite", ""))
            if len(cites) != 1 or cites[0][1] != "d":
                err(f"{where}: a figure must cite exactly one digest field ([s:<session> d:<field>])")
                continue
            session, _, ref = cites[0]
            if session not in digests:
                continue  # reported above, if cited in the text; otherwise:
            try:
                actual = field_value(digests[session], ref)
            except KeyError:
                err(f"{where}: figure cites {ref}, which session {session}'s digest doesn't have")
                continue
            if not _same(actual, fig.get("value")):
                err(f"{where}: figure says {fig.get('value')} for {ref}, the digest says {actual}")

    user = m.load("user", models_root)
    self_ = m.load("self", models_root)
    behaviors_in_report = set()
    for p in report.get("proposals") or []:
        change = p.get("model") or {}
        entry = change.get("entry") or {}
        if p.get("target") == "model" and change.get("op") == "add" and entry.get("kind") == "behavior":
            behaviors_in_report.add(entry.get("id") or p.get("id"))
    for i, p in enumerate(report.get("proposals") or []):
        result.proposals += 1
        where = f"proposal {p.get('id') or i + 1}"
        is_seed = _is_seed(p)
        check_citations(where, p.get("text", ""), require=not is_seed)
        if p.get("label") not in m.LABELS:
            err(f"{where}: label must be one of {m.LABELS}")
        target = p.get("target")
        if target not in TARGETS:
            err(f"{where}: target must be one of {TARGETS}")
        elif target == "model":
            _check_model_proposal(where, p, user, self_, behaviors_in_report, scope, err, is_seed)
        elif target == "file":
            spec = p.get("file") or {}
            if spec.get("op") not in FILE_OPS:
                err(f"{where}: file op must be one of {FILE_OPS}")
            if not _allowed_path(project_dir, spec.get("path", "")):
                err(f"{where}: {spec.get('path')} is outside the project and Claude Code's memory notes")
        elif target == "permission":
            spec = p.get("permission") or {}
            if not spec.get("allow"):
                err(f"{where}: a permission proposal names the rule to allow")
        elif target == "gameplan":
            spec = p.get("gameplan") or {}
            if spec.get("kind") not in GAMEPLAN_KINDS or not spec.get("task"):
                err(f"{where}: a gameplan proposal is a task-status or new-task with a task ID")

    if level == "monthly":
        for key in ("evolution", "lineage", "unmoved_aspirations", "model_dissents"):
            if not isinstance(report.get(key), list):
                err(f"monthly report: '{key}' must be a list (empty when there is nothing)")
        if bundle:
            for key in ("lineage", "unmoved_aspirations", "model_dissents"):
                expected = sorted(bundle.get(key) or [])
                if isinstance(report.get(key), list) and sorted(report[key]) != expected:
                    err(f"monthly report: '{key}' must list {expected or 'nothing'} (from the bundle)")
    for aid in report.get("aspirations") or []:
        entry = m.find(self_, aid)
        if not entry or entry.get("kind") != "aspiration":
            err(f"aspiration {aid} is not an aspiration in the self model")
    return result


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))
    return a == b


def _is_seed(p: dict) -> bool:
    """A first-run seed: every evidence item quotes a source file (identity or memory note)."""
    ev = ((p.get("model") or {}).get("entry") or {}).get("evidence") or []
    return bool(ev) and all(isinstance(e, dict) and e.get("source") and e.get("quote") for e in ev)


def _allowed_path(project_dir: Path, path: str) -> bool:
    if not path:
        return False
    target = Path(path)
    if not target.is_absolute():
        target = Path(project_dir) / target
    target = target.resolve()
    roots = [Path(project_dir).resolve()]
    projects = (claude_dir() / "projects").resolve()
    try:
        rel = target.relative_to(projects)
        if len(rel.parts) >= 3 and rel.parts[1] == "memory":
            return True
    except ValueError:
        pass
    return any(target == r or r in target.parents for r in roots)


def _check_model_proposal(where, p, user, self_, behaviors_in_report, scope, err, is_seed) -> None:
    change = p.get("model") or {}
    model = change.get("model")
    op = change.get("op")
    if model not in m.MODELS:
        err(f"{where}: model must be user or self")
        return
    if op not in ("add", "affirm", "revise", "retire"):
        err(f"{where}: op must be add, affirm, revise or retire")
        return
    data = user if model == "user" else self_
    entry = change.get("entry") or {}
    existing = m.find(data, change.get("id", "")) if op != "add" else None
    if op != "add" and existing is None:
        err(f"{where}: no entry {change.get('id')} in the {model} model")
        return
    subject = entry if op == "add" else {**existing, **(change.get("changes") or {})}
    entry_scope = subject.get("scope", "any")
    if entry_scope not in m.SCOPES:
        err(f"{where}: scope must be one of {m.SCOPES}")
    elif scope == "work" and entry_scope == "personal":
        err(f"{where}: a work project proposes only work or any entries, not personal ones")
    if op == "add":
        if m.is_tombstoned(data, entry.get("id"), entry.get("observation")):
            err(f"{where}: that observation was deleted or forgotten by the user; it is not proposed again")
        evidence = entry.get("evidence") or []
    else:
        evidence = change.get("evidence") or []
    if model == "user":
        category = (subject.get("category") or "").lower()
        if category in m.USER_FORBIDDEN_CATEGORIES:
            err(f"{where}: the user model holds no inferences about character, health, mood or private life")
        label = p.get("label")
        if op in ("add", "revise") and label == "inferred" and not is_seed:
            sessions = {e.get("session") for e in evidence if isinstance(e, dict)} - {None}
            if op == "revise":
                sessions |= m.evidence_sessions(existing)
            if category != m.WORKING_PREFERENCE:
                err(f"{where}: an inferred user entry must be a {m.WORKING_PREFERENCE}")
            if len(sessions) < 3:
                err(f"{where}: an inferred user entry cites at least three sessions ({len(sessions)} cited)")
    else:
        kind = subject.get("kind")
        if kind not in m.SELF_KINDS:
            err(f"{where}: a self entry's kind must be one of {m.SELF_KINDS}")
        elif kind == "aspiration":
            err(f"{where}: aspirations are written by `daedalus reflect model self aspire`, not proposed")
        elif kind == "interpretation":
            cited = {e.get("entry") for e in evidence if isinstance(e, dict)} - {None}
            if op != "add":
                cited |= {e.get("entry") for e in existing.get("evidence", []) if isinstance(e, dict)} - {None}
            known = {e["id"] for e in m.active_entries(self_) if e.get("kind") == "behavior"} | behaviors_in_report
            if not cited & known:
                err(f"{where}: an interpretation cites at least one behavior entry by ID")
            if p.get("label") != "inferred":
                err(f"{where}: an interpretation is always labelled inferred")
        elif kind == "stance":
            if change.get("identity_conflict") is not False:
                err(f"{where}: a stance must state identity_conflict: false (a stance never conflicts with the identity)")
        if p.get("label") == "inferred" and kind == "behavior" and not evidence and op == "add":
            err(f"{where}: a behavior entry cites the digests it rests on")
    if op == "affirm":
        new = {e.get("session") for e in evidence if isinstance(e, dict)} - {None}
        if not new - m.evidence_sessions(existing):
            err(f"{where}: an affirmation must cite a session not already in {existing['id']}'s evidence")
