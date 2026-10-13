---
name: inhale
description: Pick up where the last context left off. Use at the start of a session or right after a compaction, before starting work. Reads the gameplan and the last session summary, checks them against the repo, and briefs the user.
allowed-tools: Bash, Read, Grep, Glob
---

# Inhale

A new context starts with nothing but what the last one wrote down. Inhaling
reads it back, checks it against reality, and tells the user where things
stand. See "Context as Breath" in CLAUDE.md.

**Defer to the project's day-start ritual.** If the project has its own
start-of-day skill or routine and the user is starting the day (a greeting,
"good morning"), use that instead; inhale is for each new context, not each
new day. **The project comes first** here too: where CLAUDE.md says something
different from a step below, follow CLAUDE.md.

## Steps, in order

1. **Gameplan.** `daedalus gameplan show`: the active phase and the next
   pending task.

2. **Last summary.** Read the latest entry in `.daedalus/session-summaries.md`
   (and the project's committed status file, if CLAUDE.md names one).

3. **Check against the repo.** `git status`, current branch,
   `git worktree list`, unpushed commits (`git log @{u}..` where there is an
   upstream), `git stash list`, and any dev servers or processes the project
   runs. Compare with the summary.
   - Flag anything the summary doesn't explain: commits, branches, worktrees
     or changes it doesn't mention may be another session's work in the same
     clone.
   - **If the last session didn't exhale** (no summary, a summary older than
     the latest commits, or a repo the summary doesn't explain), say so
     plainly, then reconstruct what you can from `git log`, branches and
     uncommitted changes. Mark what is reconstructed versus recorded.

4. **Memory and lessons.** Read the memory index and the lessons section of
   CLAUDE.md (and any memory notes the summary or gameplan points to).

5. **Brief the user**, in a few lines: where things stand, the next task, what
   is waiting on whom, and anything that changed underneath.

6. **Wait.** Start work only on a next step the summary records as approved
   by the user. Otherwise ask which thread to pick up.
