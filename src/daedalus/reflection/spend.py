"""
Where the tokens go: a spend estimate over session digests (edict 0010, reflection).

Raw token counts don't compare: a cache read costs a tenth of fresh input, output costs five
times as much, and an Opus token several Haiku tokens. So each digest's tokens are weighted into
**units**, where one unit is one fresh input token on Haiku. The weights are API list-price
ratios (Opus 5 : Sonnet 3 : Haiku 1 for input; output 5x input; cache read 0.1x; cache write
1.25x for the 5-minute cache and 2x for the 1-hour one). How a subscription's usage limits weigh
tokens isn't published, so units are an estimate of *relative* spend, never a price.

Everything here is computed from digests. No model calls, no transcripts.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

FAMILY_WEIGHT = {"opus": 5.0, "sonnet": 3.0, "haiku": 1.0}
UNKNOWN_FAMILY_WEIGHT = 5.0  # an unrecognised model is weighed as the dearest, so it isn't hidden
CLASS_WEIGHT = {"input": 1.0, "output": 5.0, "cache_read": 0.1,
                "cache_creation_5m": 1.25, "cache_creation_1h": 2.0}
# A turn on the top model with a short prompt and at most this many tool calls: maybe one a
# cheaper model would have handled. A heuristic, labelled inferred.
LIGHT_PROMPT_CHARS = 200
LIGHT_TOOL_CALLS = 1
TOP_TURNS = 10
TOKEN_KEYS = ("input", "output", "cache_read", "cache_creation", "cache_creation_5m", "cache_creation_1h")


def family(model: Optional[str]) -> Optional[str]:
    name = (model or "").lower()
    return next((f for f in FAMILY_WEIGHT if f in name), None)


def units(tokens: dict, model: Optional[str]) -> float:
    """Estimated spend of a token record (a digest `tokens` dict) on one model."""
    if not model or model == "<synthetic>":
        return 0.0
    weight = FAMILY_WEIGHT.get(family(model) or "", UNKNOWN_FAMILY_WEIGHT)
    write_1h = int(tokens.get("cache_creation_1h") or 0)
    # Writes the transcript didn't split by cache lifetime are weighed as 5-minute writes
    write_5m = max(int(tokens.get("cache_creation") or 0) - write_1h, 0)
    raw = (CLASS_WEIGHT["input"] * int(tokens.get("input") or 0)
           + CLASS_WEIGHT["output"] * int(tokens.get("output") or 0)
           + CLASS_WEIGHT["cache_read"] * int(tokens.get("cache_read") or 0)
           + CLASS_WEIGHT["cache_creation_5m"] * write_5m
           + CLASS_WEIGHT["cache_creation_1h"] * write_1h)
    return round(raw * weight, 1)


def units_by_class(tokens: dict, model: Optional[str]) -> dict:
    """The units of a token record split by class: input, output, cache_read, cache_write."""
    one = {k: 0 for k in TOKEN_KEYS}
    out = {}
    for name, keys in (("input", ("input",)), ("output", ("output",)), ("cache_read", ("cache_read",)),
                       ("cache_write", ("cache_creation", "cache_creation_1h"))):
        out[name] = units({**one, **{k: tokens.get(k, 0) for k in keys}}, model)
    return out


def units_by_model(by_model: dict) -> float:
    return round(sum(units(t, model) for model, t in (by_model or {}).items()), 1)


def _add(into: dict, tokens: dict) -> None:
    for k in TOKEN_KEYS + ("messages",):
        into[k] = into.get(k, 0) + int(tokens.get(k) or 0)


def _in(day: Optional[str], start: Optional[date], end: Optional[date]) -> bool:
    if start is None or end is None:
        return True
    return bool(day) and start.isoformat() <= day <= end.isoformat()


def summarize(digests: Iterable[dict], start: Optional[date] = None, end: Optional[date] = None,
              top: int = TOP_TURNS, project_of: Optional[dict] = None) -> dict:
    """
    The spend of the given digests, inside [start, end] when given (by each turn's local day, and
    each subagent's start). `project_of` maps session IDs to a project, for a cross-project view.
    """
    from .digest import local_day

    by_model: dict[str, dict] = {}
    main_units = sub_units = 0.0
    by_agent: dict[str, dict] = {}
    by_project: dict[str, float] = {}
    turns, compactions, sessions = [], [], set()
    no_spend = 0
    reported = 0
    hit = {"cache_read": 0, "denominator": 0}
    for d in digests:
        sid = d.get("session_id")
        project = (project_of or {}).get(sid)
        if "turns" not in d:
            no_spend += 1  # an older digest whose transcript is gone: no spend data to count
        for t in d.get("turns") or []:
            # A turn's day is its prompt's; messages before the first prompt take the session's start
            if not _in(local_day(t.get("at") or d.get("start") or ""), start, end):
                continue
            sessions.add(sid)
            for model, tokens in (t.get("tokens_by_model") or {}).items():
                _add(by_model.setdefault(model, {"main": 0.0, "subagents": 0.0, "tokens": {}})["tokens"], tokens)
                u = units(tokens, model)
                by_model[model]["main"] += u
                main_units += u
                hit["cache_read"] += int(tokens.get("cache_read") or 0)
                hit["denominator"] += sum(int(tokens.get(k) or 0) for k in ("input", "cache_read", "cache_creation"))
            if project:
                by_project[project] = by_project.get(project, 0.0) + float(t.get("units") or 0)
            turns.append({"session": sid, **({"project": project} if project else {}),
                          **{k: t.get(k) for k in ("uuid", "at", "model", "units", "tool_calls", "chars", "text")}})
        for s in (d.get("subagents") or {}).get("list") or []:
            if not _in(local_day(s.get("start") or ""), start, end):
                continue
            sessions.add(sid)
            agent = by_agent.setdefault(s.get("agent_type") or "(untyped)", {"count": 0, "units": 0.0})
            agent["count"] += 1
            for model, tokens in (s.get("tokens_by_model") or {}).items():
                _add(by_model.setdefault(model, {"main": 0.0, "subagents": 0.0, "tokens": {}})["tokens"], tokens)
                u = units(tokens, model)
                by_model[model]["subagents"] += u
                agent["units"] += u
                sub_units += u
                if project:
                    by_project[project] = by_project.get(project, 0.0) + u
        for c in d.get("compactions") or []:
            if _in(local_day(c.get("at") or ""), start, end):
                compactions.append({"session": sid, **c})
        if sid in sessions:
            reported += int((d.get("subagents") or {}).get("reported_tokens") or 0)
    total = main_units + sub_units
    by_class = {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0}
    for m, v in by_model.items():
        for k, u in units_by_class(v["tokens"], m).items():
            by_class[k] += u
    top_model = max((m for m in by_model if family(m)), key=lambda m: FAMILY_WEIGHT[family(m) or ""], default=None)
    light = [t for t in turns if top_model and t.get("model") == top_model
             and (t.get("chars") or 0) <= LIGHT_PROMPT_CHARS and (t.get("tool_calls") or 0) <= LIGHT_TOOL_CALLS]
    light_units = sum(float(t.get("units") or 0) for t in light)
    cache_write_units = by_class["cache_write"]
    pct = (lambda x: round(100 * x / total, 1) if total else None)
    return {
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "sessions": len(sessions), "turns": len(turns),
        "units": round(total, 1), "main_units": round(main_units, 1), "subagent_units": round(sub_units, 1),
        "by_model": {m: {"main": round(v["main"], 1), "subagents": round(v["subagents"], 1),
                         "share_pct": pct(v["main"] + v["subagents"]), "tokens": v["tokens"]}
                     for m, v in sorted(by_model.items(), key=lambda kv: -(kv[1]["main"] + kv[1]["subagents"]))
                     if m != "<synthetic>"},
        "by_class": {k: {"units": round(u, 1), "share_pct": pct(u)} for k, u in by_class.items()},
        "by_agent_type": {a: {"count": v["count"], "units": round(v["units"], 1), "share_pct": pct(v["units"])}
                          for a, v in sorted(by_agent.items(), key=lambda kv: -kv[1]["units"])},
        **({"by_project": {p: {"units": round(u, 1), "share_pct": pct(u)}
                           for p, u in sorted(by_project.items(), key=lambda kv: -kv[1])}} if project_of else {}),
        "cache": {"hit_rate": round(hit["cache_read"] / hit["denominator"], 4) if hit["denominator"] else None,
                  "write_units": round(cache_write_units, 1), "write_share_pct": pct(cache_write_units)},
        "compactions": {"count": len(compactions),
                        "auto": sum(1 for c in compactions if c.get("trigger") == "auto"),
                        "pre_tokens": sum(int(c.get("pre_tokens") or 0) for c in compactions)},
        "light_turns_on_top_model": {
            "model": top_model, "count": len(light), "units": round(light_units, 1), "share_pct": pct(light_units),
            "rule": f"prompt <= {LIGHT_PROMPT_CHARS} characters and <= {LIGHT_TOOL_CALLS} tool call(s)",
            "label": "inferred"},
        "top_turns": sorted(turns, key=lambda t: -float(t.get("units") or 0))[:top],
        "subagent_reported_tokens": reported,
        "digests_without_spend": no_spend,
        "notes": ["units are an estimate of relative spend from API list-price ratios, not a price "
                  "or a usage-limit figure",
                  "subagent output tokens come from their transcripts and are a lower bound",
                  "a turn is a typed prompt and everything until the next one, including replies to "
                  "background-agent notifications; it counts on its prompt's day, even past midnight",
                  "subagent_reported_tokens is per whole session, not cut to the period"]
                 + ([f"{no_spend} digest(s) predate spend data and are not counted"] if no_spend else []),
    }


def render(summary: dict, title: str = "Spend") -> str:
    """Plain text for the terminal."""
    lines = [f"{title}: {summary['units']:,.0f} units over {summary['turns']} turns in {summary['sessions']} "
             f"session(s)" + (f" ({summary['start']} to {summary['end']})" if summary.get("start") else "")]
    if not summary["turns"] and not summary["subagent_units"]:
        return lines[0] + "\nNo token usage in this period."
    lines.append(f"  main thread {summary['main_units']:,.0f}, subagents {summary['subagent_units']:,.0f}")
    lines += ["", "By model:"]
    for m, v in summary["by_model"].items():
        lines.append(f"  {m:<28} {v['share_pct'] or 0:>5}%  main {v['main']:>12,.0f}  subagents {v['subagents']:>10,.0f}")
    lines += ["", "By token class:"]
    for k, v in summary["by_class"].items():
        lines.append(f"  {k:<12} {v['share_pct'] or 0:>5}%  {v['units']:>14,.0f}")
    if summary["by_agent_type"]:
        lines += ["", "Subagents by type:"]
        for a, v in summary["by_agent_type"].items():
            lines.append(f"  {a:<20} x{v['count']:<4} {v['units']:>12,.0f}  {v['share_pct'] or 0}%")
    if summary.get("by_project"):
        lines += ["", "By project:"]
        for p, v in summary["by_project"].items():
            lines.append(f"  {v['share_pct'] or 0:>5}%  {p}")
    c, k, light = summary["cache"], summary["compactions"], summary["light_turns_on_top_model"]
    lines += ["", f"Cache: hit rate {c['hit_rate']}, writes {c['write_share_pct'] or 0}% of spend",
              f"Compactions: {k['count']} ({k['auto']} auto), {k['pre_tokens']:,} tokens of context before them"]
    if light["model"]:
        lines.append(f"Light turns on {light['model']}: {light['count']} ({light['share_pct'] or 0}% of spend; "
                     f"{light['rule']}; inferred)")
    if summary["top_turns"]:
        lines += ["", "Most expensive turns:"]
        for t in summary["top_turns"]:
            text = (t.get("text") or "").replace("\n", " ")[:70]
            lines.append(f"  {float(t.get('units') or 0):>10,.0f}  {(t.get('at') or '')[:16]}  "
                         f"{t.get('tool_calls') or 0:>3} calls  {text}")
    lines += [""] + [f"Note: {n}" for n in summary["notes"]]
    return "\n".join(lines)
