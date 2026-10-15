"""
The Momus gate (edict 0016, trigger 1): Daedalus doesn't merge a PR that no Momus trial covers.

- PostToolUse on `gh pr create`: record the PR (number -> branch, head, skip reason) in session state,
  and nudge when no trial covers the branch yet.
- PreToolUse on `gh pr merge`: deny unless a trial's `Covers: <branch> @ <sha>` names the PR's head, or
  an earlier commit followed only by docs commits; a docs-only diff, `DAEDALUS_MOMUS_SKIP="<reason>"` in
  the command, or `momus: skip <reason>` in the PR body passes (logged).

Only Claude's tool calls reach hooks, so a merge done by hand is never gated. hooks.momus_gate is
`gate` (default), `nudge` or `off`. The PR is found from session state first, then
`gh pr view` (5 s timeout: the only network call any hook makes, on a merge, which is itself one).
"""

import json
import re
from pathlib import Path

from ..core import Ctx, Line
from ..shell import commands

PR_URL = re.compile(r"/pull/(\d+)")
SKIP_ENV = re.compile(r"""DAEDALUS_MOMUS_SKIP=("[^"]+"|'[^']+'|[^\s;&|]+)""")
SKIP_BODY = re.compile(r"momus:\s*skip\s+([^\n\"'`]+)", re.IGNORECASE)
COVERS = re.compile(r"^\s*\**Covers:?\**\s*`?([^\s`@]+)`?\s*@\s*`?([0-9a-f]{7,40})", re.IGNORECASE | re.MULTILINE)
GH_TIMEOUT = 5


class _Lazy:
    """subprocess, imported on first use: it costs ~5 ms, and most hook calls never run a command."""

    def __getattr__(self, name):
        import subprocess as real

        return getattr(real, name)


subprocess = _Lazy()


def _git(cwd: Path, *args, timeout: float = 5) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:120]}")
    return r.stdout.strip()


def _gh_pr(words: list, verb: str):
    """The arguments after `gh pr <verb>` when the command runs it, else None."""
    return words[3:] if words[:3] == ["gh", "pr", verb] else None


def merge_target(command: str):
    """The argument of the first `gh pr merge` in a command line ("" for the current branch), or None."""
    for words in commands(command):
        rest = _gh_pr(words, "merge")
        if rest is not None:
            args = [a for a in rest if not a.startswith("-")]
            # flags that take a value (--subject x, -t x, --body x, -R repo) are rare here; a number or URL wins
            for a in args:
                if a.isdigit() or PR_URL.search(a):
                    return PR_URL.search(a).group(1) if PR_URL.search(a) else a
            return args[0] if args else ""
    return None


def skip_reason(text: str) -> str:
    m = SKIP_ENV.search(text or "")
    return m.group(1).strip("\"'") if m else ""


def trials_dir(ctx: Ctx) -> Path:
    return ctx.project_dir / ".daedalus" / "momus" / "trials"


def covers(ctx: Ctx) -> list:
    """(branch, sha) from every trial's Covers line."""
    out = []
    folder = trials_dir(ctx)
    if not folder.is_dir():
        return out
    for f in folder.glob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out += [(b, s) for b, s in COVERS.findall(text)]
    return out


def docs_only(paths: list) -> bool:
    return bool(paths) and all(p.endswith(".md") or p.startswith("docs/") for p in paths)


def covered(ctx: Ctx, branch: str, head: str) -> tuple:
    """(True, how) when a trial covers the branch at its head, or at an earlier commit followed only by docs
    commits; (False, why) otherwise."""
    behind = None
    for b, sha in covers(ctx):
        if b != branch:
            continue
        if head and (head.startswith(sha) or sha.startswith(head)):
            return True, f"trial at {sha[:7]}"
        try:
            _git(ctx.project_dir, "merge-base", "--is-ancestor", sha, head)
            later = _git(ctx.project_dir, "rev-list", f"{sha}..{head}").split()
            changed = _git(ctx.project_dir, "diff", "--name-only", sha, head).split()
        except (RuntimeError, OSError, subprocess.SubprocessError):
            continue
        if docs_only(changed):
            return True, f"trial at {sha[:7]}, then docs only"
        behind = len(later) if behind is None else min(behind, len(later))
    if behind is not None:
        return False, f"{behind} commit{'s' if behind != 1 else ''} since the trial"
    return False, "no Momus trial covers it"


def pr_info(ctx: Ctx, target: str) -> dict:
    """{number, branch, head, files, body} for the PR being merged: session state first, then gh."""
    prs = ctx.state.get("prs", {})
    if target and target in prs:
        rec = dict(prs[target])
    elif not target:
        branch = _git(ctx.project_dir, "rev-parse", "--abbrev-ref", "HEAD")
        rec = next((dict(r, number=n) for n, r in prs.items() if r.get("branch") == branch), {})
        if not rec:
            rec = {"branch": branch, "head": _git(ctx.project_dir, "rev-parse", "HEAD")}
    else:
        rec = {}
    if not rec.get("branch") or "files" not in rec:
        args = ["gh", "pr", "view"] + ([target] if target else []) + ["--json", "number,headRefName,headRefOid,files,body"]
        r = subprocess.run(args, cwd=ctx.project_dir, capture_output=True, text=True, timeout=GH_TIMEOUT)
        if r.returncode != 0:
            raise RuntimeError(f"gh pr view: {r.stderr.strip()[:160]}")
        data = json.loads(r.stdout)
        body_skip = SKIP_BODY.search(data.get("body") or "")
        rec = {"number": str(data.get("number", target)), "branch": data.get("headRefName", ""),
               "head": data.get("headRefOid", ""), "files": [f.get("path", "") for f in data.get("files", [])],
               "skip": body_skip.group(1).strip() if body_skip else rec.get("skip", "")}
    return rec


def _base(cwd: Path) -> str:
    """The commit the branch forked from: against origin's default branch, else main or master."""
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        try:
            return _git(cwd, "merge-base", "HEAD", ref)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            continue
    raise RuntimeError("no base branch found")


def _record_create(ctx: Ctx) -> list:
    """After `gh pr create`: remember the PR, and nudge when no trial covers the branch yet."""
    p = ctx.payload
    command = str((p.get("tool_input") or {}).get("command") or "")
    if not any(_gh_pr(w, "create") is not None for w in commands(command)):
        return []
    resp = p.get("tool_response")
    text = json.dumps(resp) if not isinstance(resp, str) else resp
    m = PR_URL.search(text or "")
    if not m:
        return []
    try:
        branch = _git(ctx.project_dir, "rev-parse", "--abbrev-ref", "HEAD")
        head = _git(ctx.project_dir, "rev-parse", "HEAD")
        files = _git(ctx.project_dir, "diff", "--name-only", _base(ctx.project_dir), head).split()
    except (RuntimeError, OSError, subprocess.SubprocessError):
        branch, head, files = "", "", None
    skip = SKIP_BODY.search(command)
    rec = {"branch": branch, "head": head, "skip": skip.group(1).strip()[:200] if skip else ""}
    if files is not None:
        rec["files"] = files
    ctx.touch().setdefault("prs", {})[m.group(1)] = rec
    if not branch or docs_only(files or []) or rec["skip"]:
        return []
    ok, _ = covered(ctx, branch, head)
    if ok:
        return []
    return [Line(f"Daedalus: no Momus trial covers {branch} yet (PR #{m.group(1)}). Run momus on it before "
                 "merging; its trial's `Covers:` line is what the merge gate checks.",
                 nudge="momus_gate:create", tool="agent:momus", cycle=head)]


def _gate(ctx: Ctx) -> list:
    command = str((ctx.payload.get("tool_input") or {}).get("command") or "")
    target = merge_target(command)
    if target is None:
        return []
    mode = ctx.settings.get("hooks", "momus_gate")
    st = ctx.touch()
    gate = st["gate"]
    reason = skip_reason(command)
    if reason:
        gate["skips"] = gate.get("skips", 0) + 1
        st.setdefault("skips", []).append({"at": ctx.now, "pr": target, "reason": reason[:200], "how": "env"})
        return []
    info = pr_info(ctx, target)
    branch, head = info.get("branch", ""), info.get("head", "")
    if info.get("skip"):
        gate["skips"] = gate.get("skips", 0) + 1
        st.setdefault("skips", []).append({"at": ctx.now, "pr": target, "reason": info["skip"][:200], "how": "body"})
        return []
    if docs_only(info.get("files") or []):
        gate["passes"] = gate.get("passes", 0) + 1
        return []
    ok, why = covered(ctx, branch, head)
    if ok:
        gate["passes"] = gate.get("passes", 0) + 1
        return []
    pr = f"PR #{info.get('number') or target}" if (info.get("number") or target) else "this PR"
    text = (f"Daedalus merge gate: {pr} ({branch} @ {head[:7]}): {why}. Run momus on the branch (its trial's "
            f"`Covers: {branch} @ <sha>` line is what this checks), or merge with "
            "DAEDALUS_MOMUS_SKIP=\"<reason>\" / put `momus: skip <reason>` in the PR body. Turn the gate off "
            "with `daedalus config hooks.momus_gate nudge`.")
    if mode == "gate":
        gate["blocks"] = gate.get("blocks", 0) + 1
        return [Line(text, kind="gate", decision="deny", limit=600)]
    return [Line(text, nudge="momus_gate:merge", tool="agent:momus", cycle=head, limit=600)]


def run_pre(ctx: Ctx) -> list:
    if ctx.payload.get("tool_name") != "Bash" or ctx.settings.get("hooks", "momus_gate") == "off":
        return []
    return _gate(ctx)


def run_post(ctx: Ctx) -> list:
    if ctx.payload.get("tool_name") != "Bash" or ctx.settings.get("hooks", "momus_gate") == "off":
        return []
    return _record_create(ctx)
