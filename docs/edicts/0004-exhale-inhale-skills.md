# Edict 0004: Exhale and inhale as plugin skills
Status: accepted
Depends on: none (the gameplan CLI, the CLAUDE.md template and its local slots, as on main)

*Drafted by Daedalus, reviewed by Momus (trial 2026-10-13, revised for its
findings), accepted by Kohl in conversation on 2026-10-13 and merged locally
without a PR.*

## Intent
The template's "Context as Breath" section describes exhaling and inhaling,
but nothing makes them happen: each session improvises, and how well the
next one picks up depends on how well the last one remembered. Ship both as
plugin skills so every project gets the same ritual, and each project adds
only what is specific to it.

## Constraints
- Two skills: `src/daedalus/plugin/skills/exhale/SKILL.md` and
  `src/daedalus/plugin/skills/inhale/SKILL.md`.
- **Installation is new and part of this edict.** No plugin skill reaches a
  project today: `get_skills_dir()` has no callers and `hydrate` handles only
  agents and the template. `hydrate` (and `init`) copy every plugin skill to
  `.claude/skills/<name>/SKILL.md` in the project, overwriting the same way
  agents are overwritten (edit detection for both is #6), and
  `hydrate --dry-run` lists the skills that would be written. `--skills /
  --no-skills` mirrors `--agents / --no-agents`.
- `plugin.yaml` lists every shipped skill: `ariadne`, `mind-palace`, `exhale`,
  `inhale` (`ariadne` is missing today).
- Generic: no project, employer or tool specifics in either skill. Project
  steps come from the project's CLAUDE.md, in the paragraph that begins "In
  this repo, exhaling cleanly means" (in the `breath` local slot). The
  session reads that paragraph for meaning; it is not an exact-string match.
- Where the project's CLAUDE.md says something different from a generic step,
  the project wins.
- Exhale writes nothing outward-facing the user hasn't approved (pushes,
  ticket updates, PR comments): it lists those as pending instead.
- Neither skill changes the wording of the template's Context as Breath
  section. That text is Kohl's.
- Inhale defers to a project's own day-start ritual when one exists, rather
  than duplicating it.
- Inhale supersedes `src/daedalus/plugin/hooks/session-start.sh`, which no
  code installs (`get_hooks_dir()` has no callers). Retiring the hook is a
  separate change.

## Acceptance criteria
- Exhale, in order: checks repo state (git status, worktrees) before trusting
  the conversation; commits finished work per the project's authorship and
  push rules, never forcing; updates the project's work tracker where it has
  one; writes a `.daedalus/session-summaries.md` entry (done, decisions and
  why, in flight, exact next step, open questions), including when there was
  nothing to commit; records shipped gameplan tasks and adds newly found ones;
  routes lessons to skills, preferences to memory, and setup changes to the
  project's upstream log; reports what was preserved and where, and what is
  pending; then suggests `/compact` with a ready-to-paste focus note.
- Inhale, in order: reads the gameplan and the latest session summary; checks
  the repo against them (branch, worktrees, unpushed commits) and flags
  anything the summary doesn't explain, such as work by another session; if
  the summary is missing, older than the latest commits, or doesn't explain
  the repo, says the last session didn't exhale and reconstructs what it can
  from git before briefing; reads the memory index and lessons; briefs the
  user in a few lines; and starts work only on a next step the summary
  records as approved.
- With no "exhaling cleanly means" paragraph in CLAUDE.md, exhale runs the
  generic steps and suggests that the project write one.
- After `daedalus hydrate`, a project has `.claude/skills/exhale/SKILL.md` and
  `.claude/skills/inhale/SKILL.md` (and the other plugin skills);
  `--no-skills` writes none; `--dry-run` writes none and lists them.
- Tests: hydrate into a temporary project installs every skill in
  `plugin.yaml`, and each listed skill exists in the package; neither new
  skill contains a term from a deny-list kept in the test (employer, product
  and ticket-system names such as ADO, Jira, UBC).

## Non-goals
- No automation: no hooks that run exhale or compact on their own. The skills
  are for the session to follow; when to compact stays the user's call.
- No changes to the gameplan or memory formats.
- No day-level rituals (good morning, end of day); those stay per project.
- No edit detection for skills here; that arrives with #6 for agents and
  skills together.
