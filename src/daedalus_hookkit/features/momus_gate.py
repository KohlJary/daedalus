"""
The Momus gate (edict 0016, trigger 1): Daedalus doesn't merge a PR that no Momus trial covers.

- PreToolUse (Bash): every `gh pr merge` the line runs (shell.parse sees `then gh pr merge`, $(...),
  bash -c, wrappers and the second of two merges) is denied unless a trial's `Covers: <branch> @ <sha>`
  names the PR's head, or an ancestor of it followed only by docs commits. A docs-only diff, a
  DAEDALUS_MOMUS_SKIP="<reason>" on that merge command, or a `momus: skip <reason>` line in the PR body
  passes (logged with its reason).
- PostToolUse after `gh pr create`: remember the PR (number -> branch, head) and nudge when no trial
  covers the branch yet.

The PR's head and files come from `gh pr view` at merge time (a merge is a network action anyway), so a
commit pushed after `gh pr create` is checked. Session state is the fallback when gh can't answer; with
neither, the gate errors and the dispatcher allows the merge with a visible notice. Only Claude's tool
calls reach hooks, so a merge by hand is never gated. hooks.momus_gate: gate (default) | nudge | off.
"""

import json
import re
from pathlib import Path

from ..core import Ctx, Line
from ..shell import parse

PR_URL = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")
SKIP_BODY = re.compile(r"^[ \t>*-]*momus:[ \t]*skip[ \t]+(\S[^\n]*)$", re.IGNORECASE | re.MULTILINE)
PLACEHOLDER = re.compile(r"^<[^>]*>|^\.\.\.$")  # <reason>, <reason> in the PR body, ...
COVERS = re.compile(r"^\s*\**Covers:?\**\s*`?([^\s`@]+)`?\s*@\s*`?([0-9a-f]{7,40})", re.IGNORECASE | re.MULTILINE)
GH_TIMEOUT = 5
MODES = ("gate", "nudge", "off")


class _Lazy:
    """subprocess, imported on first use: it costs ~5 ms, and most hook calls never run a command."""

    def __getattr__(self, name):
        import subprocess as real

        return getattr(real, name)


subprocess = _Lazy()


def mode(ctx: Ctx) -> str:
    """The setting, normalized; anything unrecognized (a hand edit) means the safe choice, gate."""
    value = ctx.settings.get("hooks", "momus_gate")
    value = str(value).strip().lower() if value is not None else "gate"
    return value if value in MODES else ("off" if value in ("false", "0", "no") else "gate")


def _git(cwd: Path, *args, timeout: float = 5) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:120]}")
    return r.stdout.strip()


def merges(command: str) -> list:
    """[(target, repo, skip_reason)] for every `gh pr merge` the line runs. target is the PR number, URL
    or branch ("" for the current branch); repo is -R/--repo or the URL's repo, if any."""
    out = []
    for cmd in parse(command or ""):
        if cmd.words[:3] != ["gh", "pr", "merge"]:
            continue
        args, target, repo, i = cmd.words[3:], None, "", 0
        while i < len(args):
            a = args[i]
            if a in ("-R", "--repo") and i + 1 < len(args):
                repo, i = args[i + 1], i + 2
                continue
            if a.startswith("--repo="):
                repo = a.split("=", 1)[1]
            elif a.startswith("-R") and len(a) > 2:  # -Ro/r and -R=o/r (pflag forms)
                repo = a[2:].lstrip("=")
            elif a in ("-t", "--subject", "-b", "--body", "-F", "--body-file", "-A", "--author-email",
                       "--match-head-commit"):
                i += 2
                continue
            elif not a.startswith("-") and target is None:
                url = PR_URL.search(a)
                target, repo = (url.group(2), url.group(1)) if url else (a, repo)
            i += 1
        out.append((target or "", repo, cmd.env.get("DAEDALUS_MOMUS_SKIP", "").strip()))
    return out


def merge_target(command: str):
    """The first merge's target ("" for the current branch), or None when the line runs no merge."""
    found = merges(command)
    return found[0][0] if found else None


def body_skip(body: str) -> str:
    """The reason of a `momus: skip <reason>` line in a PR body; a placeholder like <reason> is no reason."""
    for m in SKIP_BODY.finditer(body or ""):
        reason = m.group(1).strip().strip("`").strip()
        if reason and not PLACEHOLDER.match(reason):
            return reason
    return ""


def covers(ctx: Ctx) -> list:
    """(branch, sha) from every trial's Covers lines."""
    out = []
    folder = ctx.project_dir / ".daedalus" / "momus" / "trials"
    if not folder.is_dir():
        return out
    for f in folder.glob("*.md"):
        try:
            out += COVERS.findall(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def docs_only(paths: list) -> bool:
    """Every changed file is Markdown or under docs/ (an empty diff is not docs-only)."""
    return bool(paths) and all(p.endswith(".md") or p.startswith("docs/") for p in paths)


def _is_ancestor(cwd: Path, sha: str, head: str) -> bool:
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", sha, head], cwd=cwd, capture_output=True,
                              text=True, timeout=5).returncode == 0
    except Exception:  # no git, a timeout: not shown to be an ancestor
        return False


def covered(ctx: Ctx, branch: str, head: str) -> tuple:
    """(True, how) when a trial covers the branch at its head, or at an ancestor followed only by docs
    commits; (False, why) otherwise, saying what was found."""
    behind, orphan = None, None
    for b, sha in covers(ctx):
        if b != branch:
            continue
        if head and (head.startswith(sha) or sha.startswith(head)):
            return True, f"trial at {sha[:7]}"
        if not _is_ancestor(ctx.project_dir, sha, head):
            orphan = sha
            continue
        try:
            later = _git(ctx.project_dir, "rev-list", f"{sha}..{head}").split()
            changed = _git(ctx.project_dir, "diff", "--name-only", sha, head).split()
        except (RuntimeError, OSError):
            continue
        if docs_only(changed):
            return True, f"trial at {sha[:7]}, then docs only"
        behind = len(later) if behind is None else min(behind, len(later))
    if behind is not None:
        return False, f"{behind} commit{'s' if behind != 1 else ''} since the trial"
    if orphan:
        return False, (f"a trial at {orphan[:7]} exists but isn't in the head's history (rebased, or the head "
                       "isn't fetched here): review the new head")
    return False, "no Momus trial covers it"


def pr_info(ctx: Ctx, target: str, repo: str = "") -> dict:
    """{number, branch, head, files, skip} for the PR being merged, from gh at merge time; the PR recorded
    at `gh pr create` this session is the fallback when gh can't answer."""
    args = ["gh", "pr", "view"] + ([target] if target else []) + (["-R", repo] if repo else []) + \
        ["--json", "number,headRefName,headRefOid,files,body"]
    data, err = None, None
    try:
        r = subprocess.run(args, cwd=ctx.project_dir, capture_output=True, text=True, timeout=GH_TIMEOUT)
        if r.returncode == 0:
            data = json.loads(r.stdout)
        else:
            err = RuntimeError(f"gh pr view: {r.stderr.strip()[:160]}")
    except Exception as e:  # TimeoutExpired, no gh, bad JSON
        err = e
    if isinstance(data, dict) and data.get("headRefName") and data.get("headRefOid"):
        return {"number": str(data.get("number") or target), "branch": data["headRefName"],
                "head": data["headRefOid"], "files": [f.get("path", "") for f in data.get("files") or []],
                "skip": body_skip(data.get("body") or ""), "source": "gh"}
    rec = ctx.state.get("prs", {}).get(target) if target and not repo else None
    if rec and rec.get("branch") and rec.get("head"):
        try:  # the branch may have moved since create: its current head locally, if it has one
            rec = dict(rec, head=_git(ctx.project_dir, "rev-parse", f"refs/heads/{rec['branch']}"))
        except (RuntimeError, OSError):
            pass
        return {"number": target, **rec, "source": "session state (gh unavailable)"}
    raise err or RuntimeError(f"gh pr view {target or '(current branch)'} gave no head")


def _record_create(ctx: Ctx) -> list:
    """After `gh pr create`: remember the PR, and nudge when no trial covers the branch yet."""
    p = ctx.payload
    command = str((p.get("tool_input") or {}).get("command") or "")
    created = [c for c in parse(command) if c.words[:3] == ["gh", "pr", "create"]]
    if not created:
        return []
    resp = p.get("tool_response")
    m = PR_URL.search(resp if isinstance(resp, str) else json.dumps(resp))
    if not m:
        return []
    words = created[0].words
    head_arg = next((words[i + 1] for i, w in enumerate(words[:-1]) if w in ("-H", "--head")), "")
    try:
        branch = head_arg.split(":")[-1] or _git(ctx.project_dir, "rev-parse", "--abbrev-ref", "HEAD")
        head = _git(ctx.project_dir, "rev-parse", branch if head_arg else "HEAD")
    except (RuntimeError, OSError):
        return []
    if branch == "HEAD":
        return []
    body = "\n".join(words) + "\n" + "\n".join(created[0].heredocs)
    for inner in created[0].substs.values():
        body += "\n" + "\n".join(b for c in inner for b in c.heredocs)
    rec = {"branch": branch, "head": head, "skip": body_skip(body)}
    ctx.touch().setdefault("prs", {})[m.group(2)] = rec
    if rec["skip"]:
        return []
    ok, _ = covered(ctx, branch, head)
    if ok:
        return []
    return [Line(f"Daedalus: no Momus trial covers {branch} yet (PR #{m.group(2)}). Run momus on it before "
                 "merging; its trial's `Covers:` line is what the merge gate checks.",
                 nudge="momus_gate:create", tool="agent:momus", cycle=head)]


def _check(ctx: Ctx, target: str, repo: str, env_skip: str) -> list:
    st = ctx.touch()
    gate = st["gate"]
    if env_skip and not PLACEHOLDER.match(env_skip):
        gate["skips"] = gate.get("skips", 0) + 1
        st.setdefault("skips", []).append({"at": ctx.now, "pr": target, "reason": env_skip[:200], "how": "env"})
        return []
    info = pr_info(ctx, target, repo)
    if info.get("skip"):
        gate["skips"] = gate.get("skips", 0) + 1
        st.setdefault("skips", []).append({"at": ctx.now, "pr": info["number"], "reason": info["skip"][:200],
                                           "how": "body"})
        return []
    if docs_only(info.get("files") or []):
        gate["passes"] = gate.get("passes", 0) + 1
        return []
    branch, head = info["branch"], info["head"]
    ok, why = covered(ctx, branch, head)
    if ok:
        gate["passes"] = gate.get("passes", 0) + 1
        return []
    source = "" if info.get("source") == "gh" else f" (from {info.get('source')})"
    text = (f"Daedalus merge gate: PR #{info['number']} ({branch} @ {head[:7]}{source}): {why}. Run momus on "
            f"the branch (its trial's `Covers: {branch} @ <sha>` line is what this checks), or merge with "
            "DAEDALUS_MOMUS_SKIP=\"<reason>\" / a `momus: skip <reason>` line in the PR body. Turn the gate "
            "off with `daedalus config hooks.momus_gate nudge`.")
    if mode(ctx) == "gate":
        gate["blocks"] = gate.get("blocks", 0) + 1
        return [Line(text, kind="gate", decision="deny", limit=700)]
    return [Line(text, nudge="momus_gate:merge", tool="agent:momus", cycle=head, limit=700)]


def run_pre(ctx: Ctx) -> list:
    if ctx.payload.get("tool_name") != "Bash" or mode(ctx) == "off":
        return []
    out = []
    for target, repo, env_skip in merges(str((ctx.payload.get("tool_input") or {}).get("command") or "")):
        out += _check(ctx, target, repo, env_skip)
    return out


def run_post(ctx: Ctx) -> list:
    if ctx.payload.get("tool_name") != "Bash" or mode(ctx) == "off":
        return []
    return _record_create(ctx)
