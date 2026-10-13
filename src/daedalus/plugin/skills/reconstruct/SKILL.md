---
name: reconstruct
description: Rebuild a period the gameplan never recorded, from git. Use when daedalus doctor reports commits after the gameplan's last update, when inhale finds the last sessions didn't exhale, or when asked to recover what happened in a stretch of a project's history. Gathers evidence, has the mnemosyne agent propose gameplan entries, checks them, has Momus review them, and presents the result. Never applies anything itself.
allowed-tools: Bash, Read, Grep, Glob, Agent
---

# Reconstruct

The gameplan fell behind the code. This rebuilds the missing period as proposed gameplan
entries, each citing its commits and labelled with how sure it is, and hands them to the user.
Nothing is written to the gameplan or roadmap until the user applies it.

## Steps, in order

1. **Find the window.** Run `daedalus doctor` and `daedalus reconstruct gather`. Gather prints
   the gap (commits since the gameplan's last update) and writes a bundle under
   `.daedalus/reconstruction/`. "No gap" means there is nothing to do; say so and stop.
   - If the user asked about a specific period or person, pass `--since`, `--until` (revisions
     or `YYYY-MM-DD`) and `--author`.
   - **Long gaps:** if the gap is more than about 150 commits, don't reconstruct it in one pass.
     Split it into windows at release commits or month boundaries (`git log --format='%h %as %s'`
     shows where), run `gather --since A --until B` for each, and carry steps 2 to 4 out per
     window, oldest first. Tell the user how many windows there are before starting; each takes a
     while.

2. **Propose.** Hand each bundle to the `mnemosyne` agent: "Reconstruct from
   `<bundle path>`; write the proposal and make `daedalus reconstruct check` pass." She writes
   `.daedalus/reconstruction/proposal-*.json`.

3. **Check.** Run `daedalus reconstruct check <proposal>` yourself. It must pass; if it doesn't,
   send the errors back to mnemosyne. Note the uncited commits it reports.

4. **Review.** Hand the proposal to the `momus` agent: "Check this reconstruction against the
   repository: every hash, number, inference, and roadmap change. Per-entry verdicts (shown,
   consistent, untested, contradicted); for the strongest inferences, the cheapest test that
   would settle them." Momus writes his review under `.daedalus/momus/`. Entries he finds
   contradicted go back to mnemosyne to correct or drop; then check again.

5. **Present.** In a short report:
   - the window, and whether evidence outside git was included
   - counts by confidence, and how many commits remain uncited
   - the headline findings, especially open tasks the evidence says are done, and roadmap items
     that shipped but are still open
   - Momus's verdicts, including anything he could not confirm
   - the `needs-confirmation` items, each with its cheapest check
   - conflicts between sources

6. **Offer, don't apply.** Tell the user they can load it with
   `daedalus gameplan pending import <proposal>`, then review with `daedalus gameplan pending`
   and `apply` or `drop` each entry. Run the import only if the user asks; never apply entries
   yourself, including ones Momus marked shown.
