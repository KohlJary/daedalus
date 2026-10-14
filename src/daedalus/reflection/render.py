"""Markdown for a checked report (edict 0010): what the user reads. The JSON stays the source."""

from __future__ import annotations


def render_report(report: dict, verdicts: dict | None = None) -> str:
    verdicts = verdicts or {}
    lines = [f"# Reflection: {report.get('level')} {report.get('period')}", ""]
    if report.get("summary"):
        lines += [report["summary"], ""]
    lines += ["## Findings", ""]
    for f in report.get("findings") or []:
        lines.append(f"- **{f.get('id', '')}** ({f.get('type')}): {f.get('text', '')}")
    if not report.get("findings"):
        lines.append("No findings.")
    lines += ["", "## Proposals", ""]
    shown, left_out = 0, []
    for p in report.get("proposals") or []:
        v = verdicts.get(p.get("id"))
        v = v if isinstance(v, dict) else {"verdict": v}
        if v.get("verdict") == "contradicted":
            left_out.append(p.get("id", ""))
            continue
        note = f" ({v['note']})" if v.get("note") else ""
        lines.append(f"- **{p.get('id', '')}** [{p.get('target')}, {p.get('label')}; Momus: {v.get('verdict')}{note}]: "
                     f"{p.get('text', '')}")
        shown += 1
    if not shown:
        lines.append("No proposals.")
    if left_out:
        lines.append(f"\nLeft out, contradicted by Momus: {', '.join(left_out)}.")
    if report.get("level") == "monthly":
        lines += ["", "## Evolution", ""]
        changes = report.get("evolution") or []
        for c in changes:
            lines.append(f"- {c.get('model')} {c.get('entry_id')}: {c.get('kind')} by {c.get('by')}"
                         f"{' - ' + c['observation'] if c.get('observation') else ''}"
                         f"{' (' + c['why'] + ')' if c.get('why') else ''}")
        if not changes:
            lines.append("No model changes this month.")
        if report.get("aspirations_compared"):
            comp = report["aspirations_compared"]
            for key in ("kept", "new", "dropped"):
                if comp.get(key):
                    lines.append(f"- Aspirations {key}: {', '.join(comp[key])}")
        if report.get("lineage"):
            lines += ["", f"Self entries whose evidence is only from models no longer in use: {', '.join(report['lineage'])}"]
        if report.get("model_dissents"):
            lines += ["", f"Dissents on self entries, for the user to weigh: {', '.join(report['model_dissents'])}"]
        if report.get("unmoved_aspirations"):
            lines += ["", f"Aspirations behavior hasn't moved toward in three months: {', '.join(report['unmoved_aspirations'])}"]
    return "\n".join(lines) + "\n"
