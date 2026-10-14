# Reflection over session logs

Edict [0010](edicts/0010-reflection.md). This page is the reference: where things live, the
formats, and how to run `tick` on a timer.

## Where things live

| Path | What |
|---|---|
| `~/.claude/projects/<folder>/<session>.jsonl` | Claude Code's transcripts (or under `CLAUDE_CONFIG_DIR`). Read, never written. |
| `.daedalus/reflection/sessions/<session>.json` | One digest per session |
| `.daedalus/reflection/due.json` | What each level has covered, and what is due |
| `.daedalus/reflection/bundles/<level>-<period>.json` | What `delphi` reads for one run |
| `.daedalus/reflection/reports/<level>-<period>.json` | `delphi`'s report; `.md` is its rendering, `.verdicts.json` Momus's |
| `.daedalus/reflection/pending.json` | Proposals waiting for you |
| `.daedalus/reflection/arms.json` | The model-summary A/B test: each session's arm and seed |
| `<config dir>/models/user.json`, `self.json` | The models (`<config dir>` is `~/.config/daedalus` on Linux, `%APPDATA%\daedalus` on Windows) |
| `<config dir>/models/history.jsonl` | Every change to either model, append-only (except `forget` with `purge`) |
| `<config dir>/models/dissents.jsonl` | Dissents a session filed against a self entry |

`.daedalus/reflection/` is gitignored by `init` and `hydrate`. None of it leaves the machine.

## How a session is found

A transcript belongs to the deepest directory with a `.daedalus/` at or above the `cwd` its first
event records. Claude Code's folder names are never decoded: they turn both `/` and `.` into `-`,
so two projects can look alike. On Windows, paths are compared without regard to case or separator.

## What a digest counts

| Count | How | Label |
|---|---|---|
| tokens | each API message once, by `message.id` (one message is written as several events) | shown |
| failures | tool results with `is_error`, other than rejections and classifier denials | shown |
| `denied_by_classifier` | results saying the auto mode classifier denied the call | shown |
| `rejected_by_user` | results saying the user declined the call at a permission prompt | shown |
| interruptions | the `[Request interrupted by user]` marker | shown |
| interruptions before a reply | a prompt with no reply before the next prompt (Esc before streaming starts leaves no marker) | inferred |
| retries | the same call (same `file_path`, or same Bash command) within 5 calls after a failure | inferred |
| re-reads | a `Read` of a path already read, with no `Edit`/`Write` of it in between | inferred |
| subagents | each subagent transcript; `reported_tokens` from each background agent's completion notice | shown |

Subagent transcripts record streaming placeholders for output tokens, so their per-message output
totals are a lower bound; `reported_tokens` is the real total. Interrupting a running tool call is
not counted: it has never been captured in a real transcript.

## Citations

Findings and proposals cite `[s:<session-id> e:<event-uuid>]` (a counted event, a tool call or its
result) or `[s:<session-id> d:<digest-field>]` (a dotted field, e.g. `tools.Bash.failures`).
`daedalus reflect check` confirms every citation resolves, that a finding of a counted type cites
only events of that type, and that every figure matches its field. It cannot tell whether a
citation supports what the finding says; Momus does that.

## Running `tick` on a timer

`daedalus reflect tick` digests every project with sessions and updates what is due. Under the
default `inhale` runner it makes no model calls, so it is safe anywhere. Installing a timer is
your choice.

**cron** (Linux, macOS), nightly at 03:15:

```
15 3 * * * daedalus reflect tick >> ~/.cache/daedalus/tick.log 2>&1
```

**systemd** (user units), `~/.config/systemd/user/daedalus-tick.service` and `.timer`:

```ini
[Unit]
Description=Digest Claude Code sessions for Daedalus reflection

[Service]
Type=oneshot
ExecStart=%h/.local/bin/daedalus reflect tick
```

```ini
[Unit]
Description=Nightly Daedalus reflection tick

[Timer]
OnCalendar=*-*-* 03:15
Persistent=true

[Install]
WantedBy=timers.target
```

Then `systemctl --user enable --now daedalus-tick.timer`.

**Task Scheduler** (Windows), from a terminal:

```
schtasks /Create /SC DAILY /ST 03:15 /TN "Daedalus reflection tick" /TR "daedalus reflect tick"
```

The Windows timer and the `headless` runner's use of `claude.cmd` are documented here and not
tested in CI.

## Runners

| `reflection.runner` | What runs model calls | Allowed when |
|---|---|---|
| `inhale` (default) | nothing outside your session: `/inhale` asks, `/reflect` runs | always |
| `headless` | `claude -p` on your own account | `machine.employer` is `false` |
| `local` | a local model (arrives with T-e5; until then it behaves as `inhale`) | `machine.employer` is `false` |

`machine.employer` unset is treated as an employer's machine on purpose.
