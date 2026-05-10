"""Run digest — structured post-run summary for Wonderland projects.

Reads ``.wonderland/`` telemetry + lifecycle + artifact state and
writes a markdown digest to ``.wonderland/digests/run-NNN.md``.

Purpose: give the operator (and future-Daedalus picking up a session)
a single file to read for "what happened in the last run" without
needing to copy-paste screenshots or re-derive from raw telemetry.

The digest is consumer-facing; it doesn't need to be exhaustive.
What goes in is calibrated to "what the operator looks at first when
the run finishes" — cost, lifecycle deltas, M8 verdicts, artifact
counts. Reviewer commentary (analysis docs) still happens manually
on top of the digest.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------- #
# Public API
# ---------------------------------------------------------------------- #


def latest_run_id(project_dir: Path) -> str | None:
    """Return the most recent run_id by telemetry filename, or None."""
    telemetry_dir = project_dir / ".wonderland" / "telemetry"
    if not telemetry_dir.is_dir():
        return None
    runs = sorted(
        f.stem.removeprefix("run-")
        for f in telemetry_dir.glob("run-*.json")
    )
    return runs[-1] if runs else None


def build_digest(project_dir: Path, run_id: str) -> str:
    """Produce the markdown digest for ``run_id`` in ``project_dir``.

    Reads telemetry, lifecycle log, phase events, and artifact dirs.
    Returns the markdown string; caller decides where to write it.
    Best-effort on each data source — missing files produce empty
    sections rather than failing the whole digest.
    """
    project_dir = Path(project_dir)
    telemetry = _read_telemetry(project_dir, run_id)
    if telemetry is None:
        raise FileNotFoundError(
            f"No telemetry for run {run_id!r} in {project_dir}"
        )

    start, end = _run_window(telemetry)
    lifecycle = _lifecycle_deltas(project_dir, start, end)
    phase_outcomes = _phase_outcomes(project_dir, start, end)
    artifacts = _artifact_counts(project_dir, start, end)
    reviews = _review_summaries(project_dir, start, end)

    return _render_digest(
        project_dir=project_dir,
        run_id=run_id,
        telemetry=telemetry,
        start=start,
        end=end,
        lifecycle=lifecycle,
        phase_outcomes=phase_outcomes,
        artifacts=artifacts,
        reviews=reviews,
    )


def write_digest(project_dir: Path, run_id: str | None = None) -> Path:
    """Build the digest for ``run_id`` (default: latest) and write it
    to ``.wonderland/digests/run-NNN.md``. Returns the written path.

    Idempotent: re-writing the same run_id overwrites the file.
    """
    project_dir = Path(project_dir)
    if run_id is None:
        run_id = latest_run_id(project_dir)
        if run_id is None:
            raise FileNotFoundError(
                f"No telemetry runs in {project_dir / '.wonderland' / 'telemetry'}"
            )

    digest_dir = project_dir / ".wonderland" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    out_path = digest_dir / f"run-{run_id}.md"
    out_path.write_text(build_digest(project_dir, run_id), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------- #
# Data readers
# ---------------------------------------------------------------------- #


def _read_telemetry(project_dir: Path, run_id: str) -> dict | None:
    path = project_dir / ".wonderland" / "telemetry" / f"run-{run_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _run_window(telemetry: dict) -> tuple[datetime, datetime]:
    """First and last entry timestamps. Falls back to (now, now) if
    no entries are present (shouldn't happen on a real run, but a
    test fixture might be empty)."""
    entries = telemetry.get("entries", [])
    if not entries:
        now = datetime.now(timezone.utc)
        return now, now
    timestamps = sorted(_parse_iso(e["timestamp"]) for e in entries if e.get("timestamp"))
    return timestamps[0], timestamps[-1]


def _parse_iso(s: str) -> datetime:
    """Tolerant ISO-8601 parser. Handles ``Z`` suffix and tz-aware
    forms produced by Wonderland's various writers."""
    s = s.rstrip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _lifecycle_deltas(
    project_dir: Path, start: datetime, end: datetime
) -> list[dict]:
    """Feature lifecycle transitions that happened during the run
    window. Each entry: {feature_slug, from_state, to_state, by, at}."""
    path = project_dir / ".wonderland" / "feature-states.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("at")
            if not ts:
                continue
            try:
                ts_dt = _parse_iso(ts)
            except ValueError:
                continue
            if start <= ts_dt <= end:
                out.append(rec)
    except OSError:
        return []
    return out


def _phase_outcomes(
    project_dir: Path, start: datetime, end: datetime
) -> dict[str, str]:
    """Map of thread_id → final phase end reason for the run window.
    Used to surface which meetings hit MEETING_BUDGET vs exit_condition
    vs aborted. Last PhaseEndEvent for each thread wins."""
    path = project_dir / ".wonderland" / "phase-events.jsonl"
    if not path.is_file():
        return {}
    outcomes: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("_kind") != "PhaseEndEvent":
                continue
            ts = e.get("timestamp")
            if not ts:
                continue
            try:
                ts_dt = _parse_iso(ts)
            except ValueError:
                continue
            if not (start <= ts_dt <= end):
                continue
            tid = e.get("thread_id", "")
            reason = e.get("reason", "?")
            outcomes[tid] = reason
    except OSError:
        return {}
    return outcomes


_ARTIFACT_DIRS: tuple[tuple[str, str], ...] = (
    ("features", "feature"),
    ("tickets", "ticket"),
    ("test-scenarios", "test_scenario"),
    ("implementations", "implementation"),
    ("contract-notes", "contract_note"),
    ("reviews", "review"),
    ("architecture", "adr"),
    ("rulings", "ruling"),
    ("stories", "story"),
)


def _artifact_counts(
    project_dir: Path, start: datetime, end: datetime
) -> dict[str, int]:
    """Count artifact files in each kind-directory whose mtime falls
    inside the run window. Approximate — file mtime can drift from
    the actual emit time when the substrate re-writes a file (e.g.
    M3.5 consolidation re-emitting tickets). Good enough for a
    digest."""
    base = project_dir / ".wonderland"
    counts: dict[str, int] = {}
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    for dir_name, kind in _ARTIFACT_DIRS:
        d = base / dir_name
        if not d.is_dir():
            continue
        n = 0
        for f in d.iterdir():
            if not f.is_file():
                continue
            if f.suffix not in (".md", ".json", ".sql"):
                continue
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if start_ts <= mt <= end_ts:
                n += 1
        if n:
            counts[kind] = n
    return counts


def _review_summaries(
    project_dir: Path, start: datetime, end: datetime
) -> list[dict]:
    """Read review files modified during the run window. Each entry:
    {title, verdict, path, body_excerpt}. Excerpt is the first ~200
    characters of the review body so the digest can show what the
    review claimed without the full text."""
    review_dir = project_dir / ".wonderland" / "reviews"
    if not review_dir.is_dir():
        return []
    out: list[dict] = []
    start_ts = start.timestamp()
    end_ts = end.timestamp()
    for f in sorted(review_dir.iterdir()):
        if not f.is_file() or f.suffix != ".md":
            continue
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if not (start_ts <= mt <= end_ts):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        title, verdict = _parse_review_header(text)
        body_excerpt = _first_finding_excerpt(text)
        out.append({
            "title": title or f.stem,
            "verdict": verdict or "?",
            "path": str(f.relative_to(project_dir)),
            "body_excerpt": body_excerpt,
        })
    return out


def _parse_review_header(text: str) -> tuple[str, str]:
    """Extract title + verdict from a review markdown file.

    Wonderland reviews use either ``# Review: <title>`` or
    ``## Review NNN: <title>`` for the heading. Sub-section
    headings (``## Findings``, ``### block:``) come later and
    must NOT be matched as the title. Verdict is on a
    ``**Verdict:** <value>`` line near the top.
    """
    title = ""
    verdict = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not title:
            # Match the title heading regardless of # depth, but
            # only if it starts with "Review" (case-insensitive)
            # so section headers like "## Findings" don't match.
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
                if heading.lower().startswith("review"):
                    # "Review: foo" or "Review 001: foo" — strip the
                    # "Review[ N]?:" prefix to get the actual title.
                    after_colon = heading.split(":", 1)
                    title = (
                        after_colon[1].strip()
                        if len(after_colon) == 2
                        else heading
                    )
        if not verdict:
            for prefix in ("**Verdict:**", "**verdict:**"):
                if line.startswith(prefix):
                    verdict = line.split(prefix, 1)[1].strip()
                    break
        if title and verdict:
            break
    return title, verdict


def _first_finding_excerpt(text: str, max_chars: int = 280) -> str:
    """Return the first finding's narrative content from a review.

    Reviews have a standard shape:

        # Review: <title>
        **Verdict:** ...
        **Target files:**
        - file
        - file
        ---
        ## Findings
        ### <severity>: <finding title>
        **Location:** ...
        **Quote:** ...
        ```...```
        **Read:** <the reviewer's read>
        **Concern:** <the concern>
        **Request:** <the proposed fix>

    The most useful excerpt is the first finding's title + its
    Concern (or Read) block — that's the operator-actionable
    statement of what's wrong. Falls back to the first non-meta
    paragraph if the structured sections aren't present.
    """
    lines = text.splitlines()

    # Pass 1: structured. Find first "### " under "## Findings",
    # then prefer Concern → Read → Request as the body excerpt.
    finding_title = ""
    body = ""
    in_findings = False
    pending_field: str | None = None
    pending_text: list[str] = []

    def _flush_field(name: str, txt: str) -> None:
        nonlocal body
        if not body and name in ("concern", "read", "request"):
            body = txt.strip()

    for raw in lines:
        line = raw.strip()
        if not line:
            if pending_field is not None:
                _flush_field(pending_field, " ".join(pending_text))
                pending_field = None
                pending_text = []
            continue
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            in_findings = heading == "findings"
            continue
        if not in_findings:
            continue
        if line.startswith("### "):
            if not finding_title:
                # "### block: Foo" or "### change-required: Foo"
                rest = line[4:].strip()
                if ":" in rest:
                    finding_title = rest.split(":", 1)[1].strip()
                else:
                    finding_title = rest
            continue
        # Field detection: lines starting with "**Field:**" begin a
        # named section. Track the current field; subsequent
        # non-empty lines extend it until a blank line or new field.
        if line.startswith("**") and ":**" in line:
            if pending_field is not None:
                _flush_field(pending_field, " ".join(pending_text))
                pending_text = []
            field_end = line.index(":**")
            field_name = line[2:field_end].strip().lower()
            after = line[field_end + 3 :].strip()
            pending_field = field_name
            pending_text = [after] if after else []
            continue
        if pending_field is not None:
            # Skip code fences inside Quote blocks — they're noisy
            # and not what we want in a digest excerpt.
            if line.startswith("```"):
                pending_field = None
                pending_text = []
                continue
            pending_text.append(line)
        if body and finding_title:
            break

    if pending_field is not None and not body:
        _flush_field(pending_field, " ".join(pending_text))

    if finding_title and body:
        excerpt = f"**{finding_title}** — {body}"
    elif finding_title:
        excerpt = finding_title
    elif body:
        excerpt = body
    else:
        # Fall back to first meaningful paragraph (legacy reviews
        # without the structured shape).
        excerpt = _first_meaningful_paragraph(text, max_chars)

    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 1].rstrip() + "…"
    return excerpt


def _first_meaningful_paragraph(text: str, max_chars: int = 280) -> str:
    """Fallback for legacy review files without structured findings.
    Skips title, meta fields, and code blocks; returns the first
    real prose paragraph."""
    lines = text.splitlines()
    paragraph: list[str] = []
    in_code = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not line:
            if paragraph:
                break
            continue
        if line.startswith("#"):
            continue
        if line.startswith("**") and ":**" in line and len(line) < 100:
            continue
        if line.startswith("---"):
            continue
        if line.startswith("- "):
            # Bullet list — skip until we get prose.
            continue
        paragraph.append(line)
        if sum(len(p) for p in paragraph) > max_chars:
            break
    text_out = " ".join(paragraph).strip()
    if len(text_out) > max_chars:
        text_out = text_out[: max_chars - 1].rstrip() + "…"
    return text_out


# ---------------------------------------------------------------------- #
# Renderer
# ---------------------------------------------------------------------- #


def _render_digest(
    *,
    project_dir: Path,
    run_id: str,
    telemetry: dict,
    start: datetime,
    end: datetime,
    lifecycle: list[dict],
    phase_outcomes: dict[str, str],
    artifacts: dict[str, int],
    reviews: list[dict],
) -> str:
    total_cost = float(telemetry.get("total_cost", 0.0))
    total_calls = int(telemetry.get("total_calls", 0))
    duration_s = (end - start).total_seconds()
    duration_min = duration_s / 60.0

    # Summarize per-meeting cost from per_thread_cost. Group by meeting
    # name (extracted from thread_id). A meeting like "composition" is
    # one thread; "decomposition-<feature>" is per-feature. Pipeline-
    # mode threads ("pipe.<feature>.<meeting>-<ticket>") group by the
    # innermost meeting name.
    per_thread = telemetry.get("per_thread_cost", {})
    per_meeting = _aggregate_per_meeting(per_thread)
    per_agent = telemetry.get("per_agent", {})

    out: list[str] = []
    out.append(f"# Run digest — {run_id}\n")
    out.append(f"**Project:** `{project_dir}`  ")
    out.append(f"**Started:** {start.isoformat(timespec='seconds')}  ")
    out.append(f"**Ended:** {end.isoformat(timespec='seconds')}  ")
    out.append(
        f"**Wall-clock:** {duration_s:.0f}s ({duration_min:.1f} min)  "
    )
    out.append(f"**Total cost:** \\${total_cost:.3f}  ")
    out.append(f"**Calls:** {total_calls}\n")

    # Per-meeting
    if per_meeting:
        out.append("## Per-meeting\n")
        out.append("| Meeting | Iter | Total | Avg / iter | Range |")
        out.append("|---|---|---|---|---|")
        for name, info in sorted(per_meeting.items()):
            costs = info["costs"]
            total = sum(costs)
            avg = total / len(costs)
            mn, mx = min(costs), max(costs)
            range_str = (
                f"\\${mn:.3f} – \\${mx:.3f}"
                if len(costs) > 1
                else "—"
            )
            out.append(
                f"| {name} | {len(costs)} | \\${total:.3f} | "
                f"\\${avg:.3f} | {range_str} |"
            )
        out.append("")

    # Per-agent
    if per_agent:
        out.append("## Per-agent\n")
        out.append("| Agent | Calls | Cost |")
        out.append("|---|---|---|")
        rows = sorted(
            per_agent.items(),
            key=lambda kv: -float(kv[1].get("cost", 0.0))
            if isinstance(kv[1], dict)
            else 0,
        )
        for agent, info in rows:
            if isinstance(info, dict):
                calls = info.get("calls", 0)
                cost = info.get("cost", 0.0)
            else:
                calls = getattr(info, "calls", 0)
                cost = getattr(info, "cost", 0.0)
            out.append(f"| {agent} | {calls} | \\${float(cost):.3f} |")
        out.append("")

    # Lifecycle deltas
    if lifecycle:
        out.append("## Lifecycle deltas\n")
        for rec in lifecycle:
            slug = rec.get("feature_slug", "?")
            frm = rec.get("from_state") or "(initial)"
            to = rec.get("to_state", "?")
            by = rec.get("by", "?")
            out.append(f"- `{slug}`: {frm} → **{to}** *(by {by})*")
        out.append("")

    # Phase outcomes that ended via budget / aborted (operator pain
    # signals worth surfacing). exit_condition + succession + exhausted
    # are normal completions; budget + aborted are the ones to flag.
    notable_outcomes = {
        tid: reason
        for tid, reason in phase_outcomes.items()
        if reason in ("aborted",)
    }
    if notable_outcomes:
        out.append("## Notable phase outcomes\n")
        for tid, reason in sorted(notable_outcomes.items()):
            short = tid.split(".")[-1] if "." in tid else tid
            out.append(f"- `{short}`: **{reason}**")
        out.append("")

    # Artifacts
    if artifacts:
        out.append("## Artifacts shipped during run\n")
        for kind, n in sorted(artifacts.items()):
            out.append(f"- {n} {kind}{'s' if n != 1 else ''}")
        out.append("")

    # Reviews — surface verdicts + excerpts
    if reviews:
        out.append("## Reviews\n")
        for r in reviews:
            verdict = r["verdict"]
            badge = (
                "🚫" if verdict.lower() == "block"
                else "⚠️" if verdict.lower() == "request-changes"
                else "✅" if verdict.lower() == "approve"
                else ""
            )
            out.append(f"### {badge} {r['title']}")
            out.append(f"**Verdict:** {verdict}  ")
            out.append(f"**File:** `{r['path']}`")
            if r["body_excerpt"]:
                out.append("")
                out.append(f"> {r['body_excerpt']}")
            out.append("")

    return "\n".join(out).rstrip() + "\n"


def _aggregate_per_meeting(
    per_thread: dict[str, float],
) -> dict[str, dict]:
    """Group per_thread costs by meeting name. Strips pipeline lane
    prefix and ticket-iteration suffix so all M6 iterations roll up
    under one row regardless of which feature/ticket they belonged to.

    Examples:
      ``composition`` → meeting ``composition`` (one cost)
      ``decomposition-feat-A`` → meeting ``decomposition``
      ``pipe.feat-A.tea-party-tic-1`` → meeting ``tea-party``
    """
    groups: dict[str, list[float]] = defaultdict(list)
    for thread_id, cost in per_thread.items():
        name = _meeting_name_from_thread(thread_id)
        groups[name].append(float(cost))
    return {name: {"costs": costs} for name, costs in groups.items()}


def _meeting_name_from_thread(thread_id: str) -> str:
    """Extract the meeting name from a thread_id, stripping any
    pipeline lane prefix and per-item iteration suffix.

    Heuristic: the meeting name is the first dash-separated segment
    after stripping the ``pipe.<slug>.`` prefix. Per-item suffixes
    (``-<feature_slug>`` or ``-<ticket_slug>``) are stripped because
    we don't know the slug boundary deterministically — we use a
    known list of meeting ids from tdd-design + tdd-implement and
    match the longest prefix that exists in that list.
    """
    s = thread_id
    # Strip pipeline lane prefix.
    if s.startswith("pipe."):
        # pipe.<feature_slug>.<rest>
        parts = s.split(".", 2)
        if len(parts) == 3:
            s = parts[2]
    # Match longest known meeting id prefix.
    known = (
        "scoping",
        "composition",
        "decomposition",
        "consolidation",
        "architecture",
        "contract-negotiation",
        "tea-party",
        "implementation",
        "review",
    )
    for name in sorted(known, key=len, reverse=True):
        if s == name or s.startswith(name + "-"):
            return name
    return s
