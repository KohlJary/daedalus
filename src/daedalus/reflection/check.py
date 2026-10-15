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
# The shapes an evidence item may take in a model entry
EVIDENCE_SHAPES = ({"session", "event"}, {"session", "field"}, {"entry"}, {"aspiration"}, {"source", "quote"})


@dataclass
class CheckResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    findings: int = 0
    proposals: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


# Numbers in a finding's text: each must be backed by a figure (edict 0010: figures are checked).
# Citations, IDs, dates, times, versions and paths are not numbers in this sense.
NUMBER = re.compile(r"(?<![\w.:/#-])(\d+(?:\.\d+)?)(%?)(?![\w:/-]|\.\d)")
SPELLED = {"two": 2, "twice": 2, "three": 3, "thrice": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "thirteen": 13, "fourteen": 14,
           "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
           "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
# Numbers that sit next to a symbol the plain pattern skips: ratios (4/109), ranges (10-20), units (3x, 12KB)
RATIO = re.compile(r"(?<![\w./])(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)(?![\w./])")
RANGE = re.compile(r"(?<![\w.-])(\d+)\s*[-–]\s*(\d+)(?![\w.-])")  # integers only: 3.10-3.12 is versions
UNIT = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)(x|kb|mb|gb|k|ms|s|m|h)\b", re.IGNORECASE)
SPELLED_RE = re.compile(r"\b(" + "|".join(SPELLED) + r")\b", re.IGNORECASE)


# Digest fields that describe the session as a whole and stay true for any day of it
WHOLE_SESSION_OK = {"session_id", "models", "claude_code_versions", "branches", "start", "end", "cwd", "labels"}


def bare_numbers(text: str) -> list[tuple[float, bool, str]]:
    """(value, is_percent, as written) for each number in prose, citations and dates removed."""
    text = CITATION.sub(" ", text or "")
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.+Z-]+)?\b", " ", text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*|"
                  r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{1,2}\b", " ", text)
    text = re.sub(r"\b(?:edicts?|PR|issue|phase|exit(?:ing|ed|s)?(?: code)?|Opus|Sonnet|Haiku|Fable|Claude)"
                  r"\s+\d+(?:\.\d+)*", " ", text, flags=re.I)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,234 is one number
    extra: list[tuple[float, bool, str]] = []
    for pattern in (RATIO, RANGE):
        for m in pattern.finditer(text):
            extra += [(float(m.group(1)), False, m.group(1)), (float(m.group(2)), False, m.group(2))]
        text = pattern.sub(" ", text)
    for m in UNIT.finditer(text):
        extra.append((float(m.group(1)), False, m.group(0)))
    text = UNIT.sub(" ", text)
    out = extra + [(float(n), pct == "%", n + pct) for n, pct in NUMBER.findall(text)]
    out += [(float(SPELLED[w.lower()]), False, w) for w in SPELLED_RE.findall(text)]
    return out


def _backed(value: float, is_percent: bool, figures: list) -> bool:
    for fig in figures:
        v = fig.get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        candidates = {float(v), round(float(v), 2), round(float(v), 1), float(round(v))}
        if is_percent or 0 <= v <= 1:
            candidates |= {round(v * 100), round(v * 100, 1), round(v * 100, 2)}
        if value in candidates:
            return True
    return False


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
    # A turn is cited by its prompt's uuid; a compaction by its boundary event's
    uuids.update(t["uuid"] for t in (digest.get("turns") or []) + (digest.get("compactions") or []) if t.get("uuid"))
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

    period = None
    if level in ("daily", "weekly"):
        try:
            from .bundle import period_bounds

            p = (bundle or {}).get("period") or report.get("period")
            start, end = period_bounds(level, p)
            period = (start.isoformat(), end.isoformat())
        except (TypeError, ValueError, AttributeError):
            period = None

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
            elif kind == "e" and period and (day := (digest.get("event_days") or {}).get(ref)) \
                    and not period[0] <= day <= period[1]:
                err(f"{where}: cites event {ref} from {day}, outside the {level} period "
                    f"{period[0]}{'' if period[0] == period[1] else ' to ' + period[1]}")
            elif kind == "d":
                try:
                    field_value(digest, ref)
                except KeyError:
                    err(f"{where}: cites digest field {ref}, which session {session}'s digest doesn't have")
                    continue
                days = set((digest.get("event_days") or {}).values())
                if period and days and not all(period[0] <= d <= period[1] for d in days) \
                        and ref.split(".")[0] not in WHOLE_SESSION_OK:
                    err(f"{where}: cites {ref}, a whole-session total, but session {session} also ran outside the "
                        f"{level} period; cite its events in the period instead (the bundle's in_period)")
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
        figs = [fig for fig in f.get("figures") or [] if isinstance(fig, dict)]
        for value, is_pct, written in bare_numbers(f.get("text", "")):
            if not _backed(value, is_pct, figs):
                err(f"{where}: the number '{written}' has no figures entry (every number from a digest is "
                    "a checked figure: add {\"value\", \"cite\": \"[s:<session> d:<field>]\"})")
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
            days = set((digests[session].get("event_days") or {}).values())
            if period and days and not all(period[0] <= d <= period[1] for d in days) \
                    and ref.split(".")[0] not in WHOLE_SESSION_OK:
                err(f"{where}: figure cites {ref}, a whole-session total, but session {session} also ran outside the "
                    f"{level} period; count the period's events instead (the bundle's in_period)")

    # A dream is never evidence (edict 0013): the report may not cite or lean on one anywhere
    import json as _json

    dream_items = set()
    try:
        from .. import roadmap as _rm

        dream_items = {i["id"] for i in _rm.load_index(project_dir).get("items", [])
                       if _rm.origin(i)["source"] == "dream"}
    except Exception:
        pass
    blob = _json.dumps({k: report.get(k) for k in ("summary", "findings", "proposals")}, ensure_ascii=False)
    hit = m.DREAM_REFERENCE.search(blob)
    if hit:
        err(f"the report refers to a dream ({hit.group(0)}); a dream is never evidence (edict 0013)")
    for item_id in sorted(dream_items):
        if re.search(rf"(?<![\w-]){re.escape(item_id)}(?![\w-])", blob):
            err(f"the report cites {item_id}, a roadmap item that came from a dream; a dream is never evidence")

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
        problems = seed_problems(p) if p.get("target") == "model" else None
        is_seed = problems is not None
        for problem in problems or []:
            err(f"{where}: {problem}")
        if is_seed and p.get("label") == "shown" and not seed_quotes_the_user(p):
            err(f"{where}: a seed is shown only when it quotes the user's own words (a memory note)")
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
            why = allowed_file_target(project_dir, spec.get("path", ""))
            if why:
                err(f"{where}: {why}")
        elif target == "permission":
            spec = p.get("permission") or {}
            if not spec.get("allow"):
                err(f"{where}: a permission proposal names the rule to allow")
            elif TOO_BROAD.match(str(spec["allow"]).strip()):
                err(f"{where}: {spec['allow']} would allow a whole tool; name the command")
            if spec.get("path") not in (None, ".claude/settings.json"):
                err(f"{where}: permission proposals edit only the project's .claude/settings.json")
        elif target == "gameplan":
            spec = p.get("gameplan") or {}
            if spec.get("kind") not in GAMEPLAN_KINDS or not spec.get("task"):
                err(f"{where}: a gameplan proposal is a task-status or new-task with a task ID")

    if level == "monthly":
        for key in ("evolution", "lineage", "unmoved_aspirations", "model_dissents"):
            if not isinstance(report.get(key), list):
                err(f"monthly report: '{key}' must be a list (empty when there is nothing)")
        if bundle:
            covered = {a.get("id") for a in report.get("aspiration_movement") or [] if isinstance(a, dict)}
            for aid in bundle.get("aspirations_active") or []:
                if aid not in covered:
                    err(f"monthly report: aspiration_movement says nothing about {aid}")
            for a in report.get("aspiration_movement") or []:
                if isinstance(a, dict) and a.get("moved"):
                    check_citations(f"aspiration_movement {a.get('id')}", a.get("text", ""))
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


def identity_files() -> list[Path]:
    """Both copies of the identity: the package's, and the one init installs in the config dir."""
    from ..config import get_config_dir

    package = Path(__file__).resolve().parent.parent / "identity" / "data"
    return [d / name for d in (package, get_config_dir()) for name in ("identity.md", "identity.json")]


def _is_memory_note(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to((claude_dir() / "projects").resolve())
    except (ValueError, OSError):
        return False
    return len(rel.parts) == 3 and rel.parts[1] == "memory" and rel.suffix == ".md"


def _squash(text: str) -> str:
    return " ".join(text.split())


def seed_problems(p: dict) -> Optional[list[str]]:
    """
    None when the proposal is not a seed. Otherwise the list of reasons it is not a valid one
    (empty when it is): every evidence item quotes an identity file or a Claude Code memory note,
    and the quote is really in that file.
    """
    ev = ((p.get("model") or {}).get("entry") or {}).get("evidence") or []
    if not ev or not all(isinstance(e, dict) and "source" in e for e in ev):
        return None
    problems = []
    identities = {f.resolve() for f in identity_files()}
    for e in ev:
        source = Path(str(e.get("source", ""))).expanduser()
        if not (source.resolve() in identities or _is_memory_note(source)):
            problems.append(f"seed source {e.get('source')} is not an identity file or a Claude Code memory note")
            continue
        try:
            text = source.read_text(encoding="utf-8-sig")
        except OSError:
            problems.append(f"seed source {e.get('source')} can't be read")
            continue
        if not e.get("quote") or _squash(str(e["quote"])) not in _squash(text):
            problems.append(f"seed quote is not in {e.get('source')}")
    return problems


def seed_quotes_the_user(p: dict) -> bool:
    """A seed is `shown` only when it quotes the user's own words: a memory note, not the identity."""
    ev = ((p.get("model") or {}).get("entry") or {}).get("evidence") or []
    return bool(ev) and all(_is_memory_note(Path(str(e.get("source", ""))).expanduser()) for e in ev)


# Where a file proposal may write: skills, agents, CLAUDE.md, and memory notes. Never the identity.
FILE_TARGETS = ("CLAUDE.md", ".claude/skills/", ".claude/agents/")


def allowed_file_target(project_dir: Path, path: str) -> Optional[str]:
    """None when a file proposal may write `path`; otherwise why not."""
    if not path:
        return "no path"
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = Path(project_dir) / target
    target = target.resolve()
    if target in {f.resolve() for f in identity_files()}:
        return f"{path} is an identity file; reflection never edits it"
    if _is_memory_note(target):
        return None
    try:
        rel = target.relative_to(Path(project_dir).resolve()).as_posix()
    except ValueError:
        return f"{path} is outside the project"
    if rel == "CLAUDE.md" or rel.endswith("/CLAUDE.md") or any(
            rel.startswith(prefix) for prefix in FILE_TARGETS[1:]):
        return None
    return f"{path} is not a skill, agent, CLAUDE.md or memory note"


TOO_BROAD = re.compile(r"^(\*|[A-Za-z]+|[A-Za-z]+\(\*\)|[A-Za-z]+\(\s*\*?:?\*\s*\))$")


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
    if existing is not None and existing.get("kind") == "aspiration":
        err(f"{where}: {existing['id']} is an aspiration: Daedalus's own, not proposed against (the user may delete it)")
        return
    subject = entry if op == "add" else {**existing, **(change.get("changes") or {})}
    entry_scope = m.canon_scope(subject.get("scope"))
    project_scope = m.canon_scope(scope, "work")
    if entry_scope not in m.SCOPES:
        err(f"{where}: scope must be one of {m.SCOPES} (personal and any are read as private and anywhere)")
    elif project_scope == "work" and entry_scope == "private":
        err(f"{where}: a work project proposes only work or anywhere entries, not private ones")
    elif project_scope == "private" and entry_scope == "work":
        err(f"{where}: a private project proposes only private or anywhere entries, not work ones")
    for item in (entry.get("evidence") if op == "add" else change.get("evidence")) or []:
        keys = set(item) if isinstance(item, dict) else set()
        if not any(keys == shape for shape in EVIDENCE_SHAPES):
            err(f"{where}: evidence {item!r} is not one of {{session, event}}, {{session, field}}, "
                "{entry}, {aspiration}, {source, quote}")
    if op == "add":
        if not str(entry.get("observation") or "").strip():
            err(f"{where}: a new entry needs an observation")
        twin = m.same_observation(data, entry.get("observation", ""))
        if twin is not None:
            err(f"{where}: {twin['id']} already says this; propose an affirm with new evidence instead")
        conf = entry.get("confidence", 0.5)
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 <= conf <= 1:
            err(f"{where}: confidence is a number from 0 to 1")
        if m.is_tombstoned(data, entry.get("id"), entry.get("observation")):
            err(f"{where}: that observation was deleted or forgotten by the user; it is not proposed again")
        evidence = entry.get("evidence") or []
        if not evidence:
            err(f"{where}: a new entry cites its evidence")
    else:
        evidence = change.get("evidence") or []
    if model == "self" and op in ("add", "affirm") and not is_seed:
        ids = (entry if op == "add" else change).get("model_ids")
        if not ids or not all(isinstance(i, str) and i for i in ids):
            err(f"{where}: a self {op} records the model IDs of the sessions behind it (model_ids)")
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
            _check_identity_quotes(where, change.get("identity_checked"), err)
        if kind == "behavior" and evidence and all(
                isinstance(e, dict) and set(e) == {"aspiration"} for e in evidence):
            err(f"{where}: a behavior rests on the record, not on an aspiration alone (an aspiration filed as a behavior?)")
        if p.get("label") == "inferred" and kind == "behavior" and not evidence and op == "add":
            err(f"{where}: a behavior entry cites the digests it rests on")
    if op == "affirm":
        new = {e.get("session") for e in evidence if isinstance(e, dict)} - {None}
        if not new - m.evidence_sessions(existing):
            err(f"{where}: an affirmation must cite a session not already in {existing['id']}'s evidence")


def _check_identity_quotes(where: str, checked: Any, err) -> None:
    """A stance names the identity clauses it was checked against, quoted, so the check can see them."""
    if not isinstance(checked, list) or not checked:
        err(f"{where}: a stance quotes the identity clauses it is consistent with (identity_checked: [{{file, quote}}])")
        return
    for item in checked:
        name = Path(str((item or {}).get("file", ""))).name if isinstance(item, dict) else ""
        quote = (item or {}).get("quote", "") if isinstance(item, dict) else ""
        copies = [f for f in identity_files() if f.name == name and f.exists()]
        if not copies:
            err(f"{where}: identity_checked names {name or '?'}, which is not an identity file")
        elif not quote or not any(_squash(quote) in _squash(f.read_text(encoding="utf-8-sig")) for f in copies):
            err(f"{where}: identity_checked quote is not in {name}")
