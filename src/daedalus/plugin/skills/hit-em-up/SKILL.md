---
name: hit-em-up
description: Plan a route through the whole work board and push every eligible item as far as the project's policy allows, then report with a route table, the gates reached, one batch of outward-facing actions for approval, and an original closing verse. Use when the user says "hit em up" or asks to work through the board, the backlog or the sprint on their own. Takes a policy name (a file in policies/) and 'plan' to stop after the route.
---

# Hit 'em up

Work the board, not the person. Read every item, plan a route, and take each eligible item as far as
the policy lets you go without asking: investigation, reproduction, design draft, provisional code with
red-checked tests. Stop each item at its gate. Everything that touches other people waits in one batch
for the user's yes.

This file is policy-agnostic. The rules for what counts as the board, what you may pick up, and where you
must stop live in a policy file under 'policies/'. Read the whole policy before step 2.

## Configuration

Defaults come from the project's '.daedalus/config.json':

```json
"hitEmUp": { "policy": "daedalus", "trust": "gated", "mode": "plan", "maxItems": 6, "verse": true }
```

- 'policy': a file in 'policies/' by its first word ('daedalus' -> 'policies/daedalus.md'). Unset: read each
  policy's Detection section and use the one that matches; if none or several match, list them and ask.
- 'trust': 'trusted' or 'gated', passed to the policy (a policy may support only 'gated'). Unset: the
  policy's own default.
- 'mode': 'plan' (stop after step 4), 'go', or 'backlog' (see Backlog mode). Unset: 'plan' the first time in
  a repo (no earlier run in the report folder), 'go' afterwards.
- 'backlog': '{ "staleDays": 30, "maxItems": 40 }' for backlog mode.
- 'dryRun': true or false (default false). See Dry run.
- 'maxItems', 'verse': as below.

Arguments override config for one run: a policy name, 'trusted'/'gated', 'plan'/'go', a number, 'no-verse'.
Say in the report which values came from config and which from arguments.

## Arguments

- Policy name (overrides 'policy').
- 'plan', 'go' or 'backlog' (overrides 'mode'); 'plan' stops after step 4 (route only).
- 'dry-run' (overrides 'dryRun'): works with any mode.
- 'no-verse': skip step 9.
- A number ('3'): work at most that many items.

## Steps

1. **Load the policy.** Read it completely. Its sections follow one contract: Source, Eligibility, Ranking,
   Autonomous work, Gates, Approval batch, Definition of done. Where the policy and this file disagree, the
   policy wins; where the project's CLAUDE.md and the policy disagree, CLAUDE.md wins. A new policy is
   a file in 'policies/' with the same sections plus Detection; nothing in this file names one.

2. **Read the board** as the policy's Source says. Every item, not a sample: id, title, type, state,
   owner, and anything already done on it (branches, documentation folders, task chain, comments).

3. **Filter by Eligibility.** Keep the eligible items. Keep a list of the others with the reason
   (owned by someone else, not approved, blocked on X), because the report shows them.

4. **Plan the route.** Rank by the policy's Ranking, then:
   - cluster items that touch the same files or area, so one read of the code serves several;
   - prefer items where existing work or this session's knowledge makes the next step cheap;
   - for an item blocked at a gate, the useful work is whatever moves it once unblocked (answer
     prepared, evidence gathered), not more of the blocked step.
   Present the route as a table: order, item, cluster, current state, next step, gate it will stop at,
   effort (small/medium/large, never a duration). With 'plan', stop here.

5. **Work the route.** For each item, in order:
   - Give it its own branch and git worktree ('git worktree add') if it gets code, so items never mix.
   - Do the policy's Autonomous work up to the item's gate. Delegate mechanical, checkable work with a lot
     to read to the cheaper project agents; keep design, debugging and verification yourself.
   - Before calling an item's step done, check the claim (Momus for anything non-trivial) and red-check
     every new test.
   - Write what you produced where the policy says, as you go, so an interrupted run loses nothing.
   - Queue every outward-facing action (anything another person will see) for the approval batch with its
     exact content. Do not send it.

6. **Know when to stop.** Stop the route when the item limit is reached, when the remaining items all sit
   at gates, or when context is getting low (exhale first; the next context resumes from the report).

7. **Approval batch.** One list of every queued outward-facing action: target, action, exact content or a
   file path, and the item it serves. Numbered, so the user can answer "1-4, 6, not 5".

8. **Report.**
   - Route table with the final state of each item and the gate it reached.
   - Per item: what was done, where it lives (paths, branches, commits), evidence (test runs with numbers),
     open questions.
   - Skipped items with reasons.
   - The approval batch.
   - What changed underneath (things noticed on the board that the user should know).

9. **The verse.** Close with a short original verse in the spirit of a West Coast diss track, aimed at the
   bugs, the backlog and the code smells the run fought through. Rules:
   - Diss code, defects, process friction and the board. Never a person, a team or a client.
   - Original lines only: no quoted or lightly altered lyrics from any real song.
   - Specific beats generic: name the actual bugs and numbers from the run.
   - Terminal only. It never goes into a work item, PR, commit, chat message or document.
   - Clean enough to read aloud in a screen share.

10. **Exhale.** Record the run where the policy's Definition of done says, and update the session summary.

## Dry run

For demonstrating what a run would do, and for judging whether it's worth doing. Combine with any mode
('go dry-run', 'backlog dry-run').

- **Reads as usual:** the board, the code, the palace, read-only data queries, all of it. The analysis is
  only as good as a real run's.
- **Writes nothing outside the report folder:** no branches, worktrees, commits or pushes; no board, ticket,
  PR or chat writes; no state changes; no files in the codebase. Approval-batch entries cannot be applied in
  this run even if the user says yes; they are recorded for a real run. Policy actions that would happen
  without approval (trusted mode, autonomous work) are recorded too, not done.
- **Records each would-be action exactly:** target, action, content (or a summary for code changes: files,
  approach, tests it would add), and which rule allows it (autonomous, needs approval, trusted).
- **Adds an analysis** to the report:
  - what a real run would produce, counted (items moved to a gate, verdicts by kind, tickets it would
    suggest closing, branches and tests it would write, approvals it would ask for);
  - the effort it saves, as work units the run would take off the user (reads, investigations, drafts,
    reproductions), never as a duration;
  - the risks it would carry (verdicts with thin evidence, items touching other people's work) and how the
    gates cover them;
  - a straight recommendation: run it for real, run part of it, or don't.
- **Labels everything 'DRY RUN'**: the report title and file name ('...-dry-run.md') and the verse's last line.

## Backlog mode

The route skips what nobody is working on; backlog mode goes after exactly that. It triages instead of
building: every item the policy's Backlog section selects gets a verdict with evidence, and nothing is
changed on the board.

1. Select items with the policy's Backlog section (typically: open, not in the current sprint or untouched
   for 'staleDays', not in progress). Oldest first, up to 'backlog.maxItems'; say how many were left.
2. For each item, check and record:
   - **Age and life signs:** created, last changed, last comment, by whom.
   - **Spec:** acceptance criteria present? Testable? What is missing?
   - **The code today:** does the system already do this (search the code, the palace, the data)? Is the
     component or flow it describes still there?
   - **Overlap:** duplicates or near-duplicates among the backlog and open items; work in flight it would
     cluster with.
   - **Size:** small, medium or large if picked up as written.
3. Give each item exactly one disposition, with the evidence that decides it:
   - **already done:** the code or data shows it (cite file and line, or query and count);
   - **duplicate of X;**
   - **obsolete:** what changed underneath it;
   - **ready:** clear, testable, sized, nothing blocking;
   - **needs refinement:** the specific questions to answer;
   - **cluster with X:** best picked up together with work in flight.
   When the evidence is thin, say "unclear" and why rather than guessing.
4. Write the triage to the policy's report location as a table (item, age, disposition, evidence, next
   action) plus a short section per disposition. The approval batch holds the suggested board actions
   (comments, closes, links, re-scoping notes) for the owner to post or forward; items that belong to
   someone else only ever get suggestions.
5. Report the totals per disposition, the oldest items, and the three things most worth doing; then the
   verse, aimed at the backlog itself.

Spread the reading across cheaper agents when the backlog is large (one batch of items each, with this
checklist); verify every "already done", "duplicate" and "obsolete" verdict yourself before it goes in the
report, since those are the ones that would close someone's ticket.

## Never

- Never take an action the policy lists as a gate, however small, without the user's answer.
- Never pick up an item that belongs to someone else; list it instead.
- Never report a step as done on an unchecked claim.
