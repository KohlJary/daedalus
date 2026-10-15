"""
Dreams on disk, their IDs, the mode draw, what is due, and the dream log (edict 0013).

Layout, all local (gitignored with the rest of `.daedalus/`):
    .daedalus/dreams/<id>/meta.json     mode, the draw's seed, theme, status, counts
    .daedalus/dreams/<id>/seeds.json    the seeds and their scores
    .daedalus/dreams/<id>/dream.md      the dream (narrative: the turns, in order)
    .daedalus/dreams/<id>/waking.md     the waking pass: "## Ideas" (narrative only) and "## Picks"
    .daedalus/dreams/due.json           what the inhale brief reads: due, waiting
    .daedalus/dreams/log.jsonl          the experiment log: counts, IDs, labels, modes and dates only

A dream's ID is its date, with `-2`, `-3`... for a second dream that day. Ideas are `<id>.i<n>` and picks
`<id>.p<n>`, numbered by code from the files, never by a model.
"""

from __future__ import annotations

import json
import random
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..reflection.fsutil import append_line, atomic_write_text, file_lock, read_json, write_json

MODES = ("list", "narrative", "plain")
LABEL = ("> **Speculative.** This is a dream: not a proposal, not evidence, and not reviewed. Nothing in\n"
         "> Daedalus reads it as fact (edict 0013).\n\n")
DREAM_ID = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-\d+)?$")
ITEM_ID = re.compile(r"\b(\d{4}-\d{2}-\d{2}(?:-\d+)?)\.([ip])(\d+)\b")
NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)")
SAFE = re.compile(r"^[A-Za-z0-9_.:+\-]{0,80}$")


class DreamError(Exception):
    pass


def dreams_dir(project_dir: Path) -> Path:
    return Path(project_dir) / ".daedalus" / "dreams"


def dream_dir(project_dir: Path, dream_id: str) -> Path:
    if not DREAM_ID.match(dream_id or ""):
        raise DreamError(f"'{dream_id}' is not a dream ID (a date, maybe with -n)")
    return dreams_dir(project_dir) / dream_id


def list_dreams(project_dir: Path) -> list[str]:
    folder = dreams_dir(project_dir)
    if not folder.is_dir():
        return []
    ids = [p.name for p in folder.iterdir() if p.is_dir() and DREAM_ID.match(p.name) and (p / "meta.json").exists()]
    return sorted(ids, key=lambda i: (i[:10], int(i[11:]) if len(i) > 10 else 1))


def load_meta(project_dir: Path, dream_id: str) -> dict:
    meta = read_json(dream_dir(project_dir, dream_id) / "meta.json")
    if not isinstance(meta, dict):
        raise DreamError(f"No dream {dream_id}")
    return meta


def save_meta(project_dir: Path, dream_id: str, meta: dict) -> None:
    write_json(dream_dir(project_dir, dream_id) / "meta.json", meta)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------- the log ----------

LOG_FIELDS = {
    "start": {"record", "at", "dream", "mode", "seed", "seeds", "seed_kinds", "theme"},
    "run": {"record", "at", "dream", "mode", "models", "tokens", "temperature", "ideas", "picks", "truncated", "turns"},
    "resolution": {"record", "at", "item", "dream", "outcome"},
    "review": {"record", "at", "review", "dreams", "themes", "recurring", "elevated"},
}


def log_path(project_dir: Path) -> Path:
    return dreams_dir(project_dir) / "log.jsonl"


def _safe(value: Any, where: str) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if not SAFE.match(value):
            raise DreamError(f"{where}: {value[:40]!r} isn't an ID, label, model or date; the log holds no text")
        return
    if isinstance(value, list):
        for v in value:
            _safe(v, where)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _safe(k, where)
            _safe(v, f"{where}.{k}")
        return
    raise DreamError(f"{where}: {type(value).__name__} isn't allowed in the log")


def log(project_dir: Path, rec: dict) -> dict:
    rec = {"record": rec["record"], "at": _now(), **{k: v for k, v in rec.items() if k != "record"}}
    kind = rec["record"]
    if kind not in LOG_FIELDS:
        raise DreamError(f"unknown log record {kind!r}")
    extra = set(rec) - LOG_FIELDS[kind]
    if extra:
        raise DreamError(f"{kind} record has fields outside the allowlist: {sorted(extra)}")
    _safe(rec, kind)
    path = log_path(project_dir)
    with file_lock(path):
        append_line(path, json.dumps(rec, sort_keys=True))
    return rec


def load_log(project_dir: Path) -> list[dict]:
    path = log_path(project_dir)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------- starting a dream ----------

def next_id(project_dir: Path, today: Optional[date] = None) -> str:
    day = (today or date.today()).isoformat()
    taken = set(list_dreams(project_dir))
    if day not in taken:
        return day
    n = 2
    while f"{day}-{n}" in taken:
        n += 1
    return f"{day}-{n}"


def draw_mode(configured: str, seed: Optional[int] = None) -> tuple[str, Optional[int]]:
    """(mode, seed). `ab` draws among the modes in code; the skill text never chooses."""
    if configured in MODES:
        return configured, None
    if configured != "ab":
        raise DreamError(f"dream.mode must be one of {MODES + ('ab',)}")
    seed = seed if seed is not None else random.SystemRandom().randrange(2 ** 31)
    return random.Random(seed).choice(MODES), seed


def start(project_dir: Path, settings: dict, theme: Optional[str] = None, mode: Optional[str] = None,
          today: Optional[date] = None, seed: Optional[int] = None) -> dict:
    from .seeds import select_seeds

    dream_id = next_id(project_dir, today)
    chosen, drawn = draw_mode(mode or settings.get("mode", "ab"), seed)
    seeds = select_seeds(project_dir, settings, theme=theme, today=today)
    folder = dream_dir(project_dir, dream_id)
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "seeds.json", {"dream": dream_id, "theme": theme, "seeds": seeds})
    meta = {"id": dream_id, "mode": chosen, "seed": drawn, "configured": mode or settings.get("mode", "ab"),
            "theme": bool(theme), "status": "started", "started": _now(), "turns": 0, "chars": 0,
            "truncated": False}
    save_meta(project_dir, dream_id, meta)
    log(project_dir, {"record": "start", "dream": dream_id, "mode": chosen, "seed": drawn, "seeds": len(seeds),
                      "seed_kinds": sorted({s["kind"] for s in seeds}), "theme": bool(theme)})
    return meta


# ---------- writing the parts ----------

def _strip_label(text: str) -> str:
    return text[len(LABEL):] if text.startswith(LABEL) else text


def append_turn(project_dir: Path, dream_id: str, speaker: str, text: str, settings: dict) -> dict:
    """Narrative mode: one turn, appended in order. Refuses past dream.turns or dream.max_tokens."""
    meta = load_meta(project_dir, dream_id)
    if meta["mode"] != "narrative":
        raise DreamError("Turns are for a narrative dream; write the whole dream with `dream write`")
    if meta.get("status") != "started":
        raise DreamError(f"Dream {dream_id} is {meta.get('status')}")
    if speaker not in ("narrator", "dreamer"):
        raise DreamError("speaker is narrator or dreamer")
    turns = int(settings.get("turns", 4))
    if meta["turns"] >= turns * 2:
        raise DreamError(f"The dream has had its {turns} turns; it ends there (no early waking, no extra turns)")
    cap = int(settings.get("max_tokens", 60000)) * 4
    if meta["chars"] + len(text) > cap:
        meta["truncated"] = True
        save_meta(project_dir, dream_id, meta)
        raise DreamError(f"That turn would pass dream.max_tokens; the dream stops here and is recorded as truncated")
    path = dream_dir(project_dir, dream_id) / "dream.md"
    body = _strip_label(path.read_text(encoding="utf-8")) if path.exists() else ""
    who = "The Labyrinth" if speaker == "narrator" else "Daedalus"
    body += f"**{who}:**\n\n{text.strip()}\n\n"
    atomic_write_text(path, LABEL + body)
    meta["turns"] += 1
    meta["chars"] += len(text)
    save_meta(project_dir, dream_id, meta)
    return meta


def write_part(project_dir: Path, dream_id: str, part: str, text: str, settings: dict) -> Path:
    if part not in ("dream", "waking"):
        raise DreamError("part is dream or waking")
    meta = load_meta(project_dir, dream_id)
    if part == "dream" and meta["mode"] == "narrative":
        raise DreamError("A narrative dream is written turn by turn (`dream turn`)")
    if part == "dream" and len(text) > int(settings.get("max_tokens", 60000)) * 4:
        text = text[: int(settings.get("max_tokens", 60000)) * 4]
        meta["truncated"] = True
    path = dream_dir(project_dir, dream_id) / f"{part}.md"
    atomic_write_text(path, LABEL + _strip_label(text).strip() + "\n")
    if part == "dream":
        meta["chars"] = len(text)
    save_meta(project_dir, dream_id, meta)
    return path


def read_part(project_dir: Path, dream_id: str, part: str) -> str:
    path = dream_dir(project_dir, dream_id) / f"{part}.md"
    return _strip_label(path.read_text(encoding="utf-8")) if path.exists() else ""


# ---------- ideas and picks, numbered by code ----------

def _section(text: str, heading: str) -> Optional[str]:
    m = re.search(rf"^##\s+{heading}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return m.group(1) if m else None


def _numbered(text: str) -> list[str]:
    items, current = [], None
    for line in text.splitlines():
        m = NUMBERED.match(line)
        if m:
            current = [m.group(2)]
            items.append(current)
        elif current is not None and line.strip() and line.startswith((" ", "\t")):
            current.append(line.strip())
        elif not line.strip():
            current = None
    return [" ".join(parts) for parts in items]


def ideas(project_dir: Path, dream_id: str) -> list[dict]:
    """The dream's ideas: the numbered list in dream.md (list, plain), or the waking pass's `## Ideas`
    (narrative, whose dream is prose)."""
    meta = load_meta(project_dir, dream_id)
    if meta["mode"] == "narrative":
        text = _section(read_part(project_dir, dream_id, "waking"), "Ideas") or ""
    else:
        dream = read_part(project_dir, dream_id, "dream")
        text = _section(dream, "Ideas") or dream
    return [{"id": f"{dream_id}.i{n}", "text": t} for n, t in enumerate(_numbered(text), 1)]


def picks(project_dir: Path, dream_id: str) -> list[dict]:
    text = _section(read_part(project_dir, dream_id, "waking"), "Picks") or ""
    out = []
    for n, t in enumerate(_numbered(text), 1):
        refs = [f"{dream_id}.i{x}" for x in re.findall(r"\bi(\d+)\b", t)]
        title = re.sub(r"\*\*(.+?)\*\*.*", r"\1", t) if t.startswith("**") else t.split(". ")[0]
        out.append({"id": f"{dream_id}.p{n}", "title": title.strip().rstrip(".")[:120], "text": t, "ideas": refs})
    return out


# ---------- finishing ----------

def done(project_dir: Path, dream_id: str, models: dict, tokens: Optional[int], temperature: str = "unset") -> dict:
    meta = load_meta(project_dir, dream_id)
    folder = dream_dir(project_dir, dream_id)
    for part in ("dream", "waking"):
        if not (folder / f"{part}.md").exists():
            raise DreamError(f"Dream {dream_id} has no {part}.md yet")
    found_picks = picks(project_dir, dream_id)
    if not found_picks:
        raise DreamError("The waking pass has no `## Picks` numbered list; it must pick three to five")
    found_ideas = ideas(project_dir, dream_id)
    meta.update({"status": "done", "finished": _now(), "ideas": len(found_ideas), "picks": len(found_picks)})
    save_meta(project_dir, dream_id, meta)
    log(project_dir, {"record": "run", "dream": dream_id, "mode": meta["mode"], "models": models, "tokens": tokens,
                      "temperature": temperature, "ideas": len(found_ideas), "picks": len(found_picks),
                      "truncated": bool(meta.get("truncated")), "turns": meta.get("turns", 0)})
    refresh_due(project_dir)
    return meta


def show(project_dir: Path, dream_id: Optional[str] = None) -> str:
    """The dream for a reader. It never says which mode produced it."""
    ids = list_dreams(project_dir)
    if not ids:
        raise DreamError("No dreams yet. Run /dream, or `daedalus dream start`.")
    dream_id = dream_id or ids[-1]
    meta = load_meta(project_dir, dream_id)
    parts = [LABEL.rstrip(), "", f"# Dream {dream_id}", ""]
    dream = read_part(project_dir, dream_id, "dream")
    if dream:
        parts += [dream.strip(), ""]
    waking = read_part(project_dir, dream_id, "waking")
    if waking:
        parts += ["## On waking", "", waking.strip(), ""]
    for p in picks(project_dir, dream_id):
        parts.append(f"- {p['id']}: {p['title']}")
    parts += ["", "Applying a pick (through `daedalus source sync dream`) publishes its text into the committed "
                  "roadmap."]
    if meta.get("status") != "done":
        parts.append(f"(This dream is {meta.get('status')}.)")
    return "\n".join(parts) + "\n"


def keep(project_dir: Path, dream_id: str, include_private: bool = False, scope: str = "work") -> Path:
    """Copy a dream to docs/dreams/<id>.md, to be committed if the owner chooses."""
    seeds = read_json(dream_dir(project_dir, dream_id) / "seeds.json", {}) or {}
    if scope == "work" and not include_private and any(s.get("scope") == "private" for s in seeds.get("seeds", [])):
        raise DreamError("This dream grew from a private seed; keep it in a work project only with --include-private")
    dest = Path(project_dir) / "docs" / "dreams" / f"{dream_id}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(dest, show(project_dir, dream_id))
    return dest


# ---------- what is due ----------

def due_path(project_dir: Path) -> Path:
    return dreams_dir(project_dir) / "due.json"


def compute_due(project_dir: Path, today: Optional[date] = None) -> dict:
    """A dream is due after a reflection run newer than the last dream, at most one scheduled a day.
    Missed dreams don't pile up. `waiting` is the newest finished dream whose picks haven't been synced."""
    from ..reflection import explog

    today = today or date.today()
    ids = list_dreams(project_dir)
    metas = [load_meta(project_dir, i) for i in ids]
    last_start = max((m.get("started", "") for m in metas), default="")
    runs = [r.get("at", "") for r in explog.load(project_dir) if r.get("record") == "run"]
    newer = any(at > last_start for at in runs)
    dreamt_today = any(i[:10] == today.isoformat() for i in ids)
    waiting = next((m["id"] for m in reversed(metas) if m.get("status") == "done" and not m.get("synced")), None)
    return {"due": bool(newer and not dreamt_today), "waiting": waiting, "computed": today.isoformat()}


def refresh_due(project_dir: Path, today: Optional[date] = None) -> dict:
    state = compute_due(project_dir, today)
    if dreams_dir(project_dir).is_dir() or state["due"]:
        write_json(due_path(project_dir), state)
    return state


def brief_line(project_dir: Path) -> str:
    """One line for the inhale brief, from due.json as raw JSON: never dream content."""
    try:
        state = json.loads(due_path(project_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    parts = []
    if state.get("due"):
        parts.append("a dream is due (/dream)")
    if state.get("waiting") and DREAM_ID.match(str(state["waiting"])):
        parts.append(f"the dream from {state['waiting']} is waiting (`daedalus dream show`)")
    return "**Dream:** " + "; ".join(parts) if parts else ""


def mark_synced(project_dir: Path, dream_ids: list[str]) -> None:
    for dream_id in dream_ids:
        try:
            meta = load_meta(project_dir, dream_id)
        except DreamError:
            continue
        if not meta.get("synced"):
            meta["synced"] = True
            save_meta(project_dir, dream_id, meta)
    refresh_due(project_dir)
