"""`daedalus reflect`: reflection over session logs (edict 0010)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional

import click


def _dream_enabled(project_dir: Path) -> bool:
    from ..config import get_project_settings

    return bool(get_project_settings(project_dir, "dream").get("enabled"))


def _dream_built(project_dir: Path, period: str) -> int:
    """Dream-origin roadmap items that reached done in a month: counted by code, never by delphi (0013)."""
    from .. import roadmap as rm

    try:
        items = rm.load_index(project_dir).get("items", [])
    except rm.RoadmapError:
        return 0
    return sum(1 for i in items if rm.origin(i)["source"] == "dream" and i.get("status") == "done"
               and str(i.get("status_changed_at", "")).startswith(period))


def _settings(project_dir: Path) -> dict:
    from ..config import get_project_settings

    return get_project_settings(project_dir, "reflection")


@click.group("reflect")
def reflect():
    """Reflection over Claude Code session logs (edict 0010).

    Deterministic parts: digest, tick, due, bundle, check, pending, arm, model. The /reflect skill
    runs a reflection: bundle, the delphi agent, check, Momus, and the report.
    """


@reflect.command("digest")
@click.option("--session", "session_id", default=None, help="Only this session (default: every new or grown one)")
@click.option("--notes", default=None, help="A few lines of this session's own reflection, stored in its digest")
def reflect_digest(session_id: Optional[str], notes: Optional[str]):
    """Digest this project's sessions into .daedalus/reflection/sessions/. No model calls."""
    from ..reflection.arms import current_session_id
    from ..reflection.digest import digest_project, set_notes

    project = Path.cwd()
    if notes is not None:
        session_id = session_id or current_session_id()
        if not session_id:
            click.echo("--notes needs --session (CLAUDE_CODE_SESSION_ID is not set)", err=True)
            raise SystemExit(2)
    result = digest_project(project, only_session=session_id)
    if notes is not None:
        try:
            set_notes(project, session_id, notes)
        except FileNotFoundError as e:
            click.echo(str(e), err=True)
            raise SystemExit(1)
    click.echo(f"Digested {len(result['written'])} session(s); {len(result['unchanged'])} unchanged.")
    if not current_session_id():
        click.echo("Note: CLAUDE_CODE_SESSION_ID is not set, so sessions here get no A/B arm (recorded as none).")
    if notes is not None:
        click.echo(f"Notes written to session {session_id}'s digest.")


@reflect.command("tick")
def reflect_tick():
    """Digest every project with sessions and update what is due. Safe from cron or a timer."""
    from ..reflection.runners import resolve_runner
    from ..reflection.tick import tick

    from ..reflection.tick import run_due_headless

    runner = resolve_runner()
    results = tick()
    for project, info in results.items():
        click.echo(f"{project}: {len(info['written'])} digested, {len(info['unchanged'])} unchanged")
        for line in info["due"]:
            click.echo(f"  {line}")
    if runner.effective == "headless":
        for project, info in results.items():
            if info["due"]:
                ok = run_due_headless(Path(project))
                click.echo(f"{project}: headless reflection {'finished' if ok else 'failed'}; "
                           "the next /inhale presents the report.")
    else:
        note = f" ({runner.reason})" if runner.reason else ""
        click.echo(f"Runner: inhale{note}. Due reflections run in your next session, when you say so.")


@reflect.command("due")
@click.option("--json", "as_json", is_flag=True, help="Print the due list as JSON")
def reflect_due(as_json: bool):
    """What reflection is due, and why. Nothing when no period with sessions is uncovered."""
    from ..reflection.tick import update_due

    due = update_due(Path.cwd())
    if as_json:
        click.echo(json.dumps([d.to_dict() for d in due], indent=2))
        return
    if not due:
        click.echo("Nothing due.")
    for d in due:
        click.echo(d.describe())


@reflect.command("done")
@click.argument("level", type=click.Choice(["daily", "weekly", "monthly"]))
@click.argument("period")
@click.option("--report", "report_file", type=click.Path(dir_okay=False), default=None,
              help="The run's report, for the experiment log's counts")
@click.option("--tokens", type=int, default=None, help="Tokens the run spent (delphi and Momus, as reported)")
@click.option("--delphi-model", default=None)
@click.option("--momus-model", default=None)
@click.option("--check-iterations", type=int, default=None, help="How many times check ran before it passed")
def reflect_done(level, period, report_file, tokens, delphi_model, momus_model, check_iterations):
    """Record a finished reflection: its period stops being due, and the run goes in the experiment log."""
    from ..reflection import explog
    from ..reflection.bundle import period_bounds
    from ..reflection.due import mark_done
    from ..reflection.runners import resolve_runner

    project = Path.cwd()
    start, end = period_bounds(level, period)
    mark_done(project, level, end, period)
    explog.record_run(project, level, period, resolve_runner().effective,
                      Path(report_file) if report_file else None, tokens, delphi_model, momus_model,
                      check_iterations)
    if level == "monthly":
        explog.record_model_changes(project, period, start, end)
    click.echo(f"Recorded the {level} reflection for {period}, and logged the run.")
    if _dream_enabled(project):
        from ..dreams.store import refresh_due

        if refresh_due(project, enabled=True)["due"]:
            click.echo("A dream is now due (edict 0013): run /dream, or defer.")


@reflect.group("log", invoke_without_command=True)
@click.pass_context
def reflect_log(ctx):
    """The experiment log: runs, resolutions, arms, model changes. Counts and IDs only, no text."""
    if ctx.invoked_subcommand:
        return
    from ..reflection import explog

    for line in explog.summary(explog.load(Path.cwd())):
        click.echo(line)


@reflect_log.command("correct")
@click.argument("level", type=click.Choice(["daily", "weekly", "monthly"]))
@click.argument("period")
@click.argument("field", type=click.Choice(["models.delphi", "models.momus", "tokens", "check_iterations"]))
@click.argument("value")
def reflect_log_correct(level: str, period: str, field: str, value: str):
    """Correct a field of a logged run (e.g. the model Momus ran as). The run record is kept; the
    correction is appended and applied when the log is read."""
    from ..reflection import explog

    try:
        explog.record_correction(Path.cwd(), level, period, field, value)
    except (explog.LogError, ValueError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Corrected {field} of the {level} run for {period} to {value}.")


@reflect_log.command("export")
@click.argument("dest", type=click.Path(dir_okay=False))
def reflect_log_export(dest: str):
    """Copy the experiment log to DEST (e.g. to commit it). Committing is your choice."""
    from ..reflection import explog

    path = explog.export(Path.cwd(), Path(dest))
    click.echo(f"Exported {len(explog.load(Path.cwd()))} records to {path}")


@reflect.command("bundle")
@click.argument("level", type=click.Choice(["daily", "weekly", "monthly", "aspiration"]))
@click.argument("period")
def reflect_bundle(level: str, period: str):
    """Write what delphi reads for one run. `aspiration` is asked cold: no earlier aspirations in it."""
    from ..reflection.bundle import build_aspiration_bundle, build_bundle, write_bundle

    project = Path.cwd()
    settings = _settings(project)
    if level == "aspiration":
        bundle = build_aspiration_bundle(project, period, settings)
    else:
        bundle = build_bundle(project, level, period, settings, settings["scope"])
    path = write_bundle(project, bundle)
    click.echo(f"Bundle: {path.relative_to(project)} ({len(bundle['digests'])} sessions)")


@reflect.command("check")
@click.argument("report", type=click.Path(exists=True, dir_okay=False))
@click.option("--bundle", "bundle_file", type=click.Path(exists=True, dir_okay=False), default=None,
              help="The bundle the report was written from (monthly: its lineage and aspirations)")
def reflect_check(report: str, bundle_file: Optional[str]):
    """Validate a report's citations, figures and proposals. Exit 1 on errors."""
    from ..reflection.check import check_report
    from ..reflection.fsutil import read_json
    from ..reflection.pending import verdicts_path

    project = Path.cwd()
    data = read_json(Path(report))
    if not isinstance(data, dict):
        click.echo(f"{report} is not valid JSON", err=True)
        raise SystemExit(1)
    bundle = read_json(Path(bundle_file)) if bundle_file else None
    result = check_report(project, data, bundle=bundle, scope=_settings(project)["scope"])
    for e in result.errors:
        click.echo(f"error: {e}")
    click.echo(f"Findings: {result.findings}; proposals: {result.proposals}")
    if result.errors:
        click.echo(f"{len(result.errors)} error(s)")
        raise SystemExit(1)
    click.echo("OK. Next: Momus's verdicts, then `daedalus reflect render`.")


@reflect.command("render")
@click.argument("report", type=click.Path(exists=True, dir_okay=False))
@click.option("--bundle", "bundle_file", type=click.Path(exists=True, dir_okay=False), default=None)
def reflect_render(report: str, bundle_file: Optional[str]):
    """Write the Markdown the user reads. Needs a passing check and Momus's verdicts; leaves out contradicted proposals."""
    from ..reflection.check import check_report
    from ..reflection.fsutil import atomic_write_text, read_json
    from ..reflection.pending import VERDICTS, verdicts_path
    from ..reflection.render import render_report

    project = Path.cwd()
    data = read_json(Path(report))
    if not isinstance(data, dict):
        click.echo(f"{report} is not valid JSON", err=True)
        raise SystemExit(1)
    bundle = read_json(Path(bundle_file)) if bundle_file else None
    if check_report(project, data, bundle=bundle, scope=_settings(project)["scope"]).errors:
        click.echo("The report doesn't pass `daedalus reflect check`.", err=True)
        raise SystemExit(1)
    verdicts = read_json(verdicts_path(Path(report)), None)
    missing = [p.get("id") for p in data.get("proposals") or []
               if _verdict(verdicts, p.get("id")) not in VERDICTS]
    if not isinstance(verdicts, dict) or missing:
        click.echo(f"No Momus verdict for {', '.join(map(str, missing)) or 'the report'} "
                   f"({verdicts_path(Path(report)).name}); every proposal is reviewed before it is shown.", err=True)
        raise SystemExit(1)
    md = Path(report).with_suffix(".md")
    text = render_report(data, verdicts)
    if data.get("level") == "monthly" and _dream_enabled(project):
        text += f"\nDream-origin items built this month: {_dream_built(project, str(data.get('period')))} (counted by code).\n"
    atomic_write_text(md, text)
    click.echo(f"Report: {md}")


def _verdict(verdicts, pid):
    if not isinstance(verdicts, dict):
        return None
    v = verdicts.get(pid)
    return v.get("verdict") if isinstance(v, dict) else v


@reflect.group("pending", invoke_without_command=True)
@click.pass_context
def reflect_pending(ctx):
    """Reflection proposals waiting for the user. Separate from `gameplan pending`."""
    if ctx.invoked_subcommand:
        return
    from ..reflection.pending import load_pending

    proposals = load_pending(Path.cwd())
    if not proposals:
        click.echo("No pending reflection proposals.")
        return
    for p in proposals:
        stance = " [stance: apply on its own]" if _is_stance(p) else ""
        click.echo(f"{p['id']} [{p.get('target')}, {p.get('label')}, Momus: {p.get('verdict')}]{stance}: {p.get('text', '')}")


def _is_stance(p: dict) -> bool:
    from ..reflection.pending import is_stance

    return is_stance(p)


@reflect_pending.command("import")
@click.argument("report", type=click.Path(exists=True, dir_okay=False))
@click.option("--bundle", "bundle_file", type=click.Path(exists=True, dir_okay=False), default=None)
def reflect_pending_import(report: str, bundle_file: Optional[str]):
    """Load a checked report's proposals, with Momus's verdicts (contradicted ones are left out)."""
    from ..reflection.fsutil import read_json
    from ..reflection.pending import PendingError, import_report

    project = Path.cwd()
    bundle = read_json(Path(bundle_file)) if bundle_file else None
    try:
        added, notes = import_report(project, Path(report), bundle=bundle, scope=_settings(project)["scope"])
    except PendingError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    for p in added:
        click.echo(f"Pending {p['id']}: {p.get('text', '')}")
    for n in notes:
        click.echo(n)


@reflect_pending.command("apply")
@click.argument("proposal_id")
def reflect_pending_apply(proposal_id: str):
    """Apply one proposal (Q1, Q2, ...) or 'all' (stances excepted)."""
    from ..reflection.models import ModelError
    from ..reflection.pending import PendingError, apply

    try:
        applied, notes = apply(Path.cwd(), proposal_id)
    except (PendingError, ModelError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    for p in applied:
        click.echo(f"Applied {p['id']}: {p.get('text', '')}")
    for n in notes:
        click.echo(n)


@reflect_pending.command("drop")
@click.argument("proposal_id")
def reflect_pending_drop(proposal_id: str):
    """Discard a proposal (or 'all')."""
    from ..reflection.pending import PendingError, drop

    try:
        dropped = drop(Path.cwd(), proposal_id)
    except PendingError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    for p in dropped:
        click.echo(f"Dropped {p['id']}")


@reflect.command("arm")
@click.option("--session", "session_id", default=None, help="Default: CLAUDE_CODE_SESSION_ID")
def reflect_arm(session_id: Optional[str]):
    """This session's arm of the model-summary A/B test (on or off), chosen in code."""
    from ..config import load_config
    from ..reflection.arms import assign_arm, current_session_id

    session_id = session_id or current_session_id()
    if not session_id:
        click.echo("none (no session ID: CLAUDE_CODE_SESSION_ID is not set)")
        return
    entry = assign_arm(Path.cwd(), session_id, load_config().reflection.model_summary)
    click.echo(entry["arm"])


@reflect.command("inhale")
def reflect_inhale():
    """What inhale prints: what reflection is due, and (in the `on` arm) the models summary."""
    from ..config import load_config
    from ..reflection.arms import assign_arm, current_session_id
    from ..reflection.models import summary
    from ..reflection.runners import resolve_runner
    from ..reflection.tick import update_due

    project = Path.cwd()
    if not (project / ".daedalus").is_dir():
        return
    config = load_config()
    from ..reflection.tick import take_unpresented

    for report in take_unpresented(project):
        click.echo(f"Reflection report ready from an unattended run (present it): {report}")
    due = update_due(project)
    if due and resolve_runner(config).effective == "inhale":
        click.echo("Reflection due (ask the user: run now, or defer?):")
        for d in due:
            click.echo(f"- {d.describe()}")
    session_id = current_session_id()
    if session_id:
        arm = assign_arm(project, session_id, config.reflection.model_summary)["arm"]
        if arm == "on":
            text = summary(_settings(project)["scope"], _settings(project))
            if text:
                click.echo(text)


@reflect.command("runner")
def reflect_runner():
    """The configured and effective reflection runner, and why they differ."""
    from ..reflection.runners import resolve_runner

    r = resolve_runner()
    click.echo(f"configured: {r.configured}; effective: {r.effective}" + (f" ({r.reason})" if r.reason else ""))


class _ModelGroup(click.Group):
    """`reflect model <user|self> --history [<entry>]` (the edict's form) runs the history subcommand."""

    def parse_args(self, ctx, args):
        if len(args) >= 2 and args[1] == "--history":
            args = [args[0], "history", *args[2:]]
        return super().parse_args(ctx, args)


@reflect.group("model", cls=_ModelGroup, invoke_without_command=True)
@click.argument("which", type=click.Choice(["user", "self"]))
@click.pass_context
def reflect_model(ctx, which: str):
    """Read a model (user or self). `--history [ENTRY]` shows how it changed; subcommands edit it."""
    ctx.obj = {"model": which}
    if ctx.invoked_subcommand:
        return
    from ..reflection import models as m

    data = m.load(which)
    settings = _settings(Path.cwd())
    hl = m.half_life(which, settings)
    today = date.today()
    for e in data["entries"]:
        status = "" if e.get("status", "active") == "active" else f" [{e['status']}]"
        kind = f"{e.get('kind')}, " if e.get("kind") else ""
        conf = "aspiration" if e.get("kind") == "aspiration" else f"{m.effective_confidence(e, today, hl):.2f}"
        click.echo(f"{e['id']} ({kind}{m.canon_scope(e.get('scope'))}, {conf}){status}: {e.get('observation', '')}")
    if not data["entries"]:
        click.echo(f"The {which} model is empty.")


@reflect_model.command("history")
@click.argument("entry_id", required=False)
@click.pass_context
def reflect_model_history(ctx, entry_id: Optional[str]):
    """How the model, or one entry, has changed: every version, in order."""
    from ..reflection import models as m

    for rec in m.load_history(model=ctx.obj["model"], entry_id=entry_id):
        after = rec.get("after") or {}
        before = rec.get("before") or {}
        text = after.get("observation") or before.get("observation") or rec.get("note", "")
        click.echo(f"{rec['at'][:10]} {rec['entry_id']} {rec['kind']} by {rec['by']}: {text}")


@reflect_model.command("edit")
@click.argument("entry_id")
@click.option("--observation", default=None)
@click.option("--confidence", type=float, default=None)
@click.option("--scope", type=click.Choice(["private", "work", "anywhere", "personal", "any"]), default=None,
              help="private, work or anywhere (personal and any are the earlier names)")
@click.option("--category", default=None)
@click.pass_context
def reflect_model_edit(ctx, entry_id, observation, confidence, scope, category):
    """Edit an entry. The user's edits win. An aspiration's text is not rewritten."""
    from ..reflection import models as m

    changes = {k: v for k, v in {"observation": observation, "confidence": confidence, "scope": scope,
                                 "category": category}.items() if v is not None}
    try:
        m.user_edit(ctx.obj["model"], entry_id, changes)
    except m.ModelError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Edited {entry_id}.")


@reflect_model.command("delete")
@click.argument("entry_id")
@click.pass_context
def reflect_model_delete(ctx, entry_id):
    """Delete an entry. A tombstone keeps it from being proposed again; its history stays."""
    from ..reflection import models as m

    try:
        m.delete(ctx.obj["model"], entry_id)
    except m.ModelError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Deleted {entry_id}.")


@reflect_model.command("forget")
@click.argument("entry_id")
@click.pass_context
def reflect_model_forget(ctx, entry_id):
    """Forget a user-model entry (reflection.forget: purge also removes its history)."""
    from ..config import load_config
    from ..reflection import models as m

    if ctx.obj["model"] != "user":
        click.echo("Only the user model has forget; a self entry can be retired, or disputed with a dissent.", err=True)
        raise SystemExit(1)
    mode = load_config().reflection.forget
    try:
        entry = m.forget(entry_id, mode)
    except m.ModelError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    from ..reflection.pending import forget_queued

    dropped = forget_queued(Path.cwd(), entry)
    click.echo(f"Forgot {entry_id} ({mode})." + (f" Dropped {dropped} queued proposal(s) about it." if dropped else ""))
    click.echo("Reports and digests written before now may still mention it; delete them under "
               ".daedalus/reflection/ if they do.")


@reflect_model.command("stable")
@click.argument("entry_id")
@click.option("--off", is_flag=True, help="Let it decay again")
@click.pass_context
def reflect_model_stable(ctx, entry_id, off):
    """Mark an entry stable (it does not decay), or --off."""
    from ..reflection import models as m

    try:
        m.set_stable(ctx.obj["model"], entry_id, not off)
    except m.ModelError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"{entry_id}: stable {'off' if off else 'on'}.")


@reflect_model.command("aspire")
@click.argument("text")
@click.option("--model-id", required=True, help="The model writing it (e.g. claude-opus-5-5)")
@click.option("--period", required=True, help="The month it answers for (YYYY-MM)")
@click.pass_context
def reflect_model_aspire(ctx, text, model_id, period):
    """Write an aspiration (self model only). Daedalus's own; no pending step."""
    from ..reflection import models as m

    if ctx.obj["model"] != "self":
        click.echo("Aspirations belong to the self model.", err=True)
        raise SystemExit(1)
    entry = m.aspire(text, model_id, period)
    click.echo(f"Aspiration {entry['id']} written.")
