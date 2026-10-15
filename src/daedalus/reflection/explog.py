"""
The experiment log (edict 0010): reflection is an experiment, and every run and its outcome is
recorded so it can be judged later.

`.daedalus/reflection/experiment-log.jsonl`, append-only, written only by deterministic commands:
runs (`reflect done`), resolutions (`pending apply` / `drop`), A/B arm assignments (`reflect arm`),
and monthly model-change counts. It holds no free text: every field is on an allowlist and every
string must look like an ID, label, model or date, so the log can be shared.
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .fsutil import append_line, file_lock, read_json
from .paths import reflection_dir

SAFE_STRING = re.compile(r"^[A-Za-z0-9_.:+\-]{0,80}$")
FIELDS = {
    "run": {"record", "at", "level", "period", "runner", "models", "sessions", "session_ids", "tokens",
            "findings", "proposals", "check_iterations", "report"},
    "resolution": {"record", "at", "report", "proposal", "pending_id", "target", "label", "verdict",
                   "outcome", "days_waited"},
    "arm": {"record", "at", "session", "mode", "arm"},
    "model_changes": {"record", "at", "period", "counts"},
    # Append-only, so a mistake in a run record is corrected by a later record, never by editing it
    "correction": {"record", "at", "level", "period", "field", "value"},
}
CORRECTABLE = ("models.delphi", "models.momus", "tokens", "check_iterations")


class LogError(Exception):
    """A record that would put something other than counts, IDs and labels in the log."""


def log_path(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "experiment-log.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe(value: Any, where: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return
    if isinstance(value, str):
        if not SAFE_STRING.match(value):
            raise LogError(f"{where}: {value[:40]!r} is not an ID, label, model or date")
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            _safe(v, f"{where}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _safe(k, f"{where} key")
            _safe(v, f"{where}.{k}")
        return
    raise LogError(f"{where}: {type(value).__name__} is not allowed in the log")


def validate(rec: dict) -> None:
    kind = rec.get("record")
    if kind not in FIELDS:
        raise LogError(f"unknown record type {kind!r}")
    extra = set(rec) - FIELDS[kind]
    if extra:
        raise LogError(f"{kind} record has fields outside the allowlist: {sorted(extra)}")
    _safe(rec, kind)


def append(project_dir: Path, rec: dict) -> dict:
    rec = {"record": rec["record"], "at": _now(), **{k: v for k, v in rec.items() if k != "record"}}
    validate(rec)
    path = log_path(project_dir)
    with file_lock(path):
        append_line(path, json.dumps(rec, sort_keys=True))
    return rec


def load(project_dir: Path) -> list[dict]:
    path = log_path(project_dir)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------- the records ----------


def record_run(project_dir: Path, level: str, period: str, runner: str, report_path: Optional[Path] = None,
               tokens: Optional[int] = None, delphi_model: Optional[str] = None,
               momus_model: Optional[str] = None, check_iterations: Optional[int] = None) -> dict:
    from .pending import verdicts_path

    findings: Counter = Counter()
    proposals = []
    session_ids: set = set()
    if report_path and Path(report_path).exists():
        report = read_json(Path(report_path), {}) or {}
        verdicts = read_json(verdicts_path(Path(report_path)), {}) or {}
        from .check import citations

        for f in report.get("findings") or []:
            findings[str(f.get("type", "other"))] += 1
            session_ids.update(c[0] for c in citations(f.get("text", ""))[0])
        for p in report.get("proposals") or []:
            v = verdicts.get(p.get("id"))
            v = v.get("verdict") if isinstance(v, dict) else v
            change = p.get("model") or {}
            proposals.append({"id": p.get("id"), "target": p.get("target"), "label": p.get("label"),
                              "verdict": v, "model": change.get("model"), "op": change.get("op"),
                              "kind": (change.get("entry") or {}).get("kind")})
    from .bundle import bundles_dir

    bundle = read_json(bundles_dir(project_dir) / f"{level}-{period}.json", {}) or {}
    covered = sorted({d.get("session_id") for d in bundle.get("digests", []) if d.get("session_id")}) or sorted(session_ids)
    return append(project_dir, {
        "record": "run", "level": level, "period": period, "runner": runner,
        "models": {"delphi": delphi_model, "momus": momus_model},
        "sessions": len(covered), "session_ids": covered, "tokens": tokens,
        "findings": dict(findings), "proposals": proposals, "check_iterations": check_iterations,
        "report": Path(report_path).name if report_path else None,
    })


def record_resolution(project_dir: Path, p: dict, outcome: str) -> dict:
    created = p.get("created")
    waited = (date.today() - date.fromisoformat(created)).days if created else None
    return append(project_dir, {
        "record": "resolution", "report": p.get("report"), "proposal": p.get("report_proposal"),
        "pending_id": p.get("id"), "target": p.get("target"), "label": p.get("label"),
        "verdict": p.get("verdict"), "outcome": outcome, "days_waited": waited,
    })


def record_arm(project_dir: Path, session_id: str, entry: dict) -> dict:
    return append(project_dir, {"record": "arm", "session": session_id, "mode": entry.get("mode"),
                                "arm": entry.get("arm")})


def record_model_changes(project_dir: Path, period: str, start: date, end: date,
                         root: Optional[Path] = None) -> dict:
    from . import models as m

    counts: Counter = Counter()
    for rec in m.load_history(root):
        day = rec.get("at", "")[:10]
        if day and start.isoformat() <= day <= end.isoformat():
            counts[str(rec.get("kind"))] += 1
    return append(project_dir, {"record": "model_changes", "period": period, "counts": dict(counts)})


def record_correction(project_dir: Path, level: str, period: str, field: str, value: Any) -> dict:
    """Correct one field of an earlier run record. The run record stays; readers apply the latest correction."""
    if field not in CORRECTABLE:
        raise LogError(f"Only {', '.join(CORRECTABLE)} can be corrected")
    runs = [r for r in load(project_dir) if r.get("record") == "run" and r.get("level") == level and r.get("period") == period]
    if not runs:
        raise LogError(f"No {level} run for {period} in the log")
    if field in ("tokens", "check_iterations"):
        value = int(value)
        if not 0 <= value < 10 ** 9:
            raise LogError(f"{field} must be between 0 and 10^9")
    elif not str(value).strip():
        raise LogError("a model ID can't be empty")
    return append(project_dir, {"record": "correction", "level": level, "period": period, "field": field,
                                "value": value})


def corrected(records: list[dict]) -> list[dict]:
    """The run records with later corrections applied (the file itself is never rewritten)."""
    import copy

    out = copy.deepcopy(records)
    latest: dict = {}  # (level, period) -> the newest run *before* this point in the file
    for rec in out:
        key = (rec.get("level"), rec.get("period"))
        if rec.get("record") == "run":
            latest[key] = rec
            continue
        if rec.get("record") != "correction":
            continue
        c, run = rec, latest.get(key)
        if run is None:
            continue
        if c["field"].startswith("models."):
            run.setdefault("models", {})[c["field"].split(".", 1)[1]] = c["value"]
        else:
            run[c["field"]] = c["value"]
    return out


# ---------- reading it back ----------


def summary(records: list[dict]) -> list[str]:
    records = corrected(records)
    runs = [r for r in records if r.get("record") == "run"]
    res = [r for r in records if r.get("record") == "resolution"]
    arms = [r for r in records if r.get("record") == "arm"]
    lines = [f"Runs: {len(runs)} ({', '.join(f'{k} {v}' for k, v in sorted(Counter(r['level'] for r in runs).items())) or 'none'})"]
    spent = [r["tokens"] for r in runs if isinstance(r.get("tokens"), int)]
    if spent:
        lines.append(f"Tokens per run: mean {sum(spent) // len(spent)}, total {sum(spent)} ({len(spent)} runs reported)")
    models = Counter(f"{k} {v}" for r in runs for k, v in sorted((r.get("models") or {}).items()) if v)
    if models:
        lines.append("Models: " + ", ".join(f"{k} ({n})" for k, n in sorted(models.items())))
    proposed = [p for r in runs for p in r.get("proposals", [])]
    verdicts = Counter(p.get("verdict") for p in proposed)
    if proposed:
        lines.append(f"Proposals: {len(proposed)}; Momus: " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items(), key=str)))
    if res:
        lines.append("Resolved: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["outcome"] for r in res).items())))
        for key in ("target", "label"):
            groups: dict = {}
            for r in res:
                groups.setdefault(r.get(key), Counter())[r["outcome"]] += 1
            parts = []
            for k, c in sorted(groups.items(), key=lambda kv: str(kv[0])):
                total = c["applied"] + c["dropped"]
                parts.append(f"{k} {c['applied']}/{total}")
            lines.append(f"Applied by {key}: " + ", ".join(parts))
    if arms:
        lines.append("A/B arms: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(f"{r.get('mode')}:{r.get('arm')}" for r in arms).items())))
    return lines


def export(project_dir: Path, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = log_path(project_dir)
    if src.exists():
        shutil.copyfile(src, dest)
    else:
        dest.write_text("", encoding="utf-8")
    return dest
