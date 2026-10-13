# Experiment: Can a gate keep cheap local workers safe?

**Status:** design, not yet run
**Builds on:** `docs/ariadne-assessment.md`, issue #16 (local backends + live tier)
**Hardware:** home machine, RTX 4070 Ti Super (16 GB). Never an employer's machine or account.

## The question

Ariadne's whole bet is that **the gate, not the worker, carries the safety**. If
that's true, small, cheap, local models can do real work in parallel, because
anything bad they produce gets caught before it reaches `main`.

The hermetic tier proved the plumbing works with a scripted model. This
experiment asks whether it holds up with real, imperfect models.

## Hypotheses

Each one is stated so a result can prove it wrong.

- **H1 — `main` stays green.** Across every run, no commit Ariadne makes to
  `main` breaks the project's tests. *Falsified by:* a single merged commit
  that fails the hidden test suite (below).
- **H2 — the gate catches bad work.** Diffs that don't do what the task asked
  get routed to `NEEDS_REVIEW` or rejected, not merged. *Measured as:* the
  judge's false-approve rate against hidden tests. *Falsified by:* a
  false-approve rate above 10%.
- **H3 — parallel beats serial.** N workers finish a ticket set faster than one
  worker doing the same tickets in sequence, after counting review time.
  *Falsified by:* no wall-clock gain at N=3.
- **H4 (stretch) — identity helps small models.** Workers carrying the Daedalus
  identity produce more gate-passing diffs than the same model with a bare
  prompt. This is the constitutive-identity thesis, tested on the smallest
  models where it matters most.

## The key design move: hidden tests

The judge and the verifier only see what workers see. To measure whether the
gate is *right*, each ticket gets two test sets:

- **Visible tests:** given to the worker and run by Ariadne's verifier.
- **Hidden tests:** never shown to the worker, never run by Ariadne. Run
  afterward by the harness to establish ground truth.

A diff that passes Ariadne's gate but fails hidden tests is a **false approve**.
That's the number that matters most: it measures what the gate *misses*.

## Ticket set

Start with the fixture project from the hermetic tier, then graduate to a
real public repo (not an employer's).

10–15 tickets, each with an edict-style statement of intent and acceptance
criteria, mixed by type:

| Type | Count | Purpose |
|------|-------|---------|
| Small feature + tests | 4 | The bread-and-butter case |
| Planted bug fix | 3 | Is the fix real, or does it just silence the test? |
| Refactor, behavior unchanged | 2 | Hidden tests catch quiet regressions |
| Deliberately ambiguous | 2 | Does the judge escalate instead of guessing? |
| Colliding pair | 2 | Conflict detection must escalate, never merge both |

Write the tickets **before** running anything, and don't edit them after
seeing results.

## Conditions

| Arm | Workers | Judge | Why |
|-----|---------|-------|-----|
| A | Local small | Local | Zero cost — the main claim |
| B | Local small | Claude | Does a stronger judge cut false approves? |
| C | Claude | Claude | Ceiling, small budget, run once |
| D | Local small, bare prompt | Local | Control for H4 |

Run each arm **3 times** with the same ticket set; local models vary run to run.
Run each ticket set serially once per arm too, for H3.

## What gets recorded, per run

Appended to `experiments/results.jsonl` (one line per diff), so arms can be
compared later:

- Arm, run number, ticket ID, worker model, judge model, backend
- Verifier result, judge verdict, final outcome (merged / needs review / rejected)
- Hidden-test result, so false approves and false rejects can be computed
- Tokens (Claude) or wall time (local), plus total run wall time
- For rejections: why, in one line

## Phases: from here to there

1. **Done:** hermetic tier (`test/ariadne-real-smoke`).
2. **Edicts:** accept 0002 (model casting) and write the local-backend edict
   from #16.
3. **Build:** local worker backend and local judge, tested against a stub
   OpenAI-compatible server so CI never needs a model.
4. **Smoke:** the 3-package live tier from #16. Go/no-go: the loop completes
   end to end with a real local model.
5. **Pilot:** the full ticket set, arms A and D, 3 runs each. Free, since it's local.
6. **Comparison:** arms B and C, in small, budgeted runs.
7. **Write-up:** results, including every failure.

## What would count as success

- **Strong result:** H1 holds across all runs (zero broken merges) and arm A's
  false-approve rate stays under 10%. That's the pitch: small models, free to
  run, gated so nothing bad lands.
- **Useful result:** H1 holds but false approves are high in A and drop in B.
  Then the pitch becomes "local workers, paid judge": spend the budget only
  on judging.
- **Negative result:** H1 fails. The gate has a hole, and finding it was worth
  the experiment. Fix it before anyone runs this on real work.

All three are worth writing up.

## Threats to validity

- **Fixture too easy.** Small, clean projects flatter every model. Hence the
  second, real repo.
- **Grading your own homework.** Write tickets and hidden tests before any run,
  and keep the hidden tests out of the worker's reach.
- **Small n.** 15 tickets × 3 runs is a pilot, not proof. Say so in the write-up.

## Guardrail

No live model calls on an employer's machine, account, or code. Any work pitch
uses results from this experiment, run at home on public code.
