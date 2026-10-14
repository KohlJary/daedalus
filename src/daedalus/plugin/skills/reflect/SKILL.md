---
name: reflect
description: Run a due reflection over this project's Claude Code session logs. Use when inhale reports a daily, weekly or monthly reflection is due and the user says to run it, or when the user asks how recent work went. Builds the bundle, has the delphi agent write a report, checks it, has Momus review the proposals, and presents them. At the monthly level also asks, cold, who Daedalus wants to be. Never applies a proposal itself.
allowed-tools: Bash, Read, Grep, Glob, Agent
---

# Reflect

Claude Code keeps a transcript of every session; `daedalus reflect digest` keeps a digest of
each. Reflection reads them back and asks what the record shows: where work was slow or failed,
what keeps recurring, and what that says about the user and about Daedalus. Its output is
proposals. Nothing changes until the user applies one.

Run it only when the user has said to (inhale asks: run now, or defer?). Deferring leaves it due.

## Steps, in order

1. **What is due.** `daedalus reflect digest`, then `daedalus reflect due`. Run the highest level
   first; it covers the lower ones in its period. Nothing due means nothing to do: say so and stop.

2. **Bundle.** `daedalus reflect bundle <level> <period>`.

3. **Monthly only: aspirations, asked cold.** Before the report:
   `daedalus reflect bundle aspiration <month>`, then hand that bundle to the `delphi` agent:
   "Answer the aspiration bundle at `<path>`: who do you want to be? Write your aspirations with
   `daedalus reflect model self aspire`. Don't read the self model or earlier reports first."
   Keep her answer's aspiration IDs for the next step.

4. **Report.** Hand the level bundle to `delphi`: "Reflect on `<bundle path>`; write the report
   and make `daedalus reflect check <report> --bundle <bundle>` pass." At the monthly level, add
   the aspiration IDs from step 3 and ask her to compare them with the earlier aspirations in
   the bundle (kept, new, dropped).

5. **Check.** Run `daedalus reflect check <report> --bundle <bundle>` yourself. It must pass; if
   it doesn't, send the errors back to delphi.

6. **Review.** Hand the report to `momus`: "Review this reflection report against its digests
   and the models: does each citation support its finding; is each proposal warranted; does any
   self-model proposal flatter Daedalus, or run it down, beyond the record? Write per-proposal
   verdicts (shown, consistent, untested, contradicted) next to the report, as
   `<level>-<period>.verdicts.json`: `{"R1": {"verdict": "...", "note": "..."}}`." Proposals he finds contradicted go back to
   delphi to correct or drop; then check again.

   Add to the prompt: "Check that no aspiration is presented as a behavior, and that each
   stance's `identity_checked` quotes really support it."

7. **Render and record.** `daedalus reflect render <report> --bundle <bundle>` writes the Markdown
   the user reads, with the verdicts and without contradicted proposals; it refuses until every
   proposal has a verdict. Then record the run, which also writes it to the experiment log:
   `daedalus reflect done <level> <period> --report <report> --tokens <N> --delphi-model <id>
   --momus-model <id> --check-iterations <n>`. Take the tokens from the delphi and Momus
   completion notices (their totals added up), and the models from what each ran as.

8. **Present.** Briefly: the period, the headline findings, and each proposal with its label and
   Momus's verdict. At the monthly level, the Evolution section (how the models changed and
   why), the aspirations and how they compare with last month's, and any lineage or unmoved
   aspirations flagged. Then the Markdown report's path.

9. **Offer, don't apply.** The user can load the proposals with
   `daedalus reflect pending import <report> --bundle <bundle>`, review them with
   `daedalus reflect pending`, and `apply` or `drop` each one. Stances are applied one at a time.
   Run the import only if the user asks; never apply a proposal yourself.
