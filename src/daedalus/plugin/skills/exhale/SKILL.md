---
name: exhale
description: Preserve the session's work so the next context can pick up without asking. Use at a natural breakpoint (work handed off for review, waiting on someone, before a large new task), when context is running low, or before /compact. Ends by suggesting /compact.
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Exhale

The work is already done; exhaling makes sure it is findable. What the next
context needs must live in commits, the work tracker, the gameplan and memory
files, not in this conversation. See "Context as Breath" in CLAUDE.md.

**The gameplan is the record of state.** What is built, in progress and next
goes there first; the session summary is the narrative around it and refers
to gameplan tasks by ID instead of restating them.

**The project comes first.** Read the paragraph in CLAUDE.md that begins
"In this repo, exhaling cleanly means" (usually in the `breath` local slot)
and follow it. Where it says something different from a step below, the
project wins. If there is no such paragraph, run the steps below and, at the
end, suggest that the project write one.

**Nothing outward-facing without approval.** Pushes, ticket or task updates,
PR comments, messages: do only what the user has already approved in this
session. List everything else as pending in the report.

## Steps, in order

1. **Repo state first.** Run `git status`, `git worktree list` and
   `git log --oneline -5` (and `git stash list`). Trust what they show over
   what the conversation remembers. If there are changes you didn't make,
   another session may share the clone: stop and tell the user before
   committing anything.

2. **Commit finished work.** Functional title, reasoning in the body, per the
   project's authorship and sign-off rules in CLAUDE.md. Commit only files you
   changed, by path. Push only where the project and the user allow; never
   force. Half-finished work: leave it uncommitted (or on a WIP branch if the
   project does that) and say so in the report.

3. **Work tracker.** If the project tracks work outside git (tickets, task
   descriptions, an issue list), bring what this session changed up to date,
   within what the user approved. Otherwise list the updates as pending.

4. **Gameplan.** For each shipped task:
   `daedalus gameplan task status <id> done --resolution "..."` (what shipped,
   with commit hashes). Mark work you started `in_progress`. Add tasks for work
   discovered this session: `daedalus gameplan task add <id> "Title"
   --details "..."` (and, in projects that use edicts, `--edict NNNN` when it implements one). If
   `daedalus gameplan pending` lists proposals, apply the ones this session
   confirms and drop the wrong ones. Finish with `daedalus doctor`; anything it
   reports about the gameplan is unfinished exhaling.

5. **Session summary.** Append an entry to `.daedalus/session-summaries.md`,
   even when there was nothing to commit. Refer to gameplan tasks by ID rather
   than restating them:
   - **Done:** the tasks closed (by ID), plus anything outside the gameplan,
     with commit hashes, PR or task links
   - **Decisions:** what was decided and why (also add lasting ones to
     `.daedalus/decisions.md`)
   - **In flight:** branches, worktrees, uncommitted work, anything waiting on
     someone
   - **Next step:** the exact next action (a task ID where there is one), and
     whether the user approved it
   - **Open questions** for the user

6. **Digest the session.** While the context is still here, run
   `daedalus reflect digest --notes "<two or three lines>"`: what went slowly
   or wrong this session and why, in your own words, with no flattery and no
   self-punishment. It digests the session's transcript (no model calls) and
   stores the notes in its digest, for the next reflection to read. Don't run a
   full reflection here. If `CLAUDE_CODE_SESSION_ID` isn't set, pass
   `--session <id>` (the transcript's file name), or skip the notes.

7. **Other workstreams** (when `daedalus workstream others` prints any). Release claims on
   paths this session finished with (`daedalus workstream claim --release
   <paths>`) and commit the change. For board threads still waiting on your
   workstream, draft replies (`daedalus board draft`) and list them as pending
   the owner's approval; never post them yourself.

8. **Route what was learned.**
   - A lesson learned the hard way -> the skill or CLAUDE.md lessons section
     where the next session will see it
   - A user preference or correction -> a memory note
   - A change to the Daedalus setup itself (template, agents, skills, these
     rituals) -> the project's upstream-changes log, if it keeps one

9. **Report.** In a few lines: what was preserved and where, what is in
   flight, what is pending approval, anything left uncommitted and why.

10. **Suggest compaction.** Offer `/compact` with a ready-to-paste focus note,
   e.g. `/compact keep the PR review plan and the hold on pushing; drop the
   test-run output`. Once per breakpoint; when to compact is the user's call.
