# Ophanic perception: does a box-drawing diagram help a model see structure?

*Designed 2026-10-15 at Kohl's request ("an experiment to actually test drive ophanic perception on various
axes"). This is a pre-registration. The hypotheses and the analysis are fixed here, before any data.*

## Why
The case for Ophanic rests on three things:
- a thesis: text grids are what transformers read best;
- one manual A/B, in `~/ophanic/ab-test/RESULTS.md`: the same model, one run, scored by its author;
- how it felt to design the TUI.

Edict 0017 would make Ophanic Daedalus's spatial language. Before structure gets drawn by default, there should
be evidence about where diagrams help, where they don't, and what they cost.

## What is compared
The same structure, with the same ground truth, is given to a model in one of four **encodings**:

| Encoding | What it is |
|---|---|
| `ophanic` | a box-drawing diagram in Daedalus's conventions (edict 0017): nesting as boxes, edges as `─▶` with slugs and a legend |
| `prose` | sentences a person would write ("The sidebar is on the left, a quarter of the width...") |
| `json` | the generator's own data, as nested JSON |
| `list` | an indented Markdown outline for nesting, and an edge list for graphs |

`json` and `list` are the strong controls. If Ophanic only beats prose, all that shows is that structure beats
prose, not that the drawing does.

## Axes
1. **Structure type.**
   - `layout`: nested rows and columns with proportions, like a UI.
   - `graph`: a DAG with labelled edges, like edict dependencies.
   - `containment`: groups holding items, some items in two groups, like workstreams and claims.
2. **Size:** small (5-8 elements), medium (15-25) and large (40-60).
3. **Question kind**, each with one checkable answer:
   - spatial: what is directly right of / below X;
   - proportion: X's share of its row, scored correct within ±5 points;
   - containment: is X inside Y; what holds X;
   - count: how many in G;
   - path: does A reach B; the shortest path length;
   - aggregate: which nodes have no dependents.
4. **Width:** the diagram at 100 or at 60 columns. Narrow forces wrapping and abbreviation.
5. **Noise** (ophanic only): a clean diagram, versus one with a ragged row and a broken join. Does a small drawing
   error mislead the model?
6. **Cost:** the input tokens per encoding for the same structure, measured by the model API's own count where it
   reports one, else estimated (bytes / 4) and labelled as an estimate.
7. **Model.**
   - Local: qwen3:8b, plus qwen3:14b if VRAM allows.
   - Claude: Haiku, Sonnet and Opus, only after Kohl starts the paid runs (no paid Claude runs before 2026-10-23).
8. **Construction** (phase 2): given a JSON structure, the model draws the diagram. Scored on `daedalus oph check`
   passing, and on structure fidelity: every name present, every containment and adjacency right, recovered by the
   rectangle detector in `score.py`.

## Hypotheses and falsifiers
- **H1 (spatial):** on `layout` spatial and proportion questions, `ophanic` beats `prose` and `list`.
  *Falsified if* its accuracy is not higher than both by at least 10 points at medium size, pooled over models.
- **H2 (graphs):** on `graph` path questions, `ophanic` does no better than `json` or `list`. A drawing is not an
  advantage for multi-hop reasoning. *Falsified if* `ophanic` beats both by at least 10 points.
- **H3 (size):** the `ophanic` advantage on `layout` grows with size (small, then medium, then large). *Falsified if*
  it shrinks or reverses.
- **H4 (noise):** one ragged row or broken join costs `ophanic` less than 5 points of accuracy. *Falsified if* it
  costs 5 or more.
- **H5 (cost):** `ophanic` costs at least 1.5 times the input tokens of `json` for the same structure. This is
  descriptive, and sets the price of any accuracy gain.
- **H6 (construction):** at least 80% of model-drawn diagrams pass `oph check`, and at least 70% have every
  containment right. *Falsified if* either falls short.

## Method
- `generate.py` makes tasks from a fixed seed: a structure, its encodings, its questions and their answers. It is
  deterministic: the same seed gives the same tasks.
- `run.py` sends each (task, encoding, question) to a model with the same instruction: "Answer with only the answer."
  It runs at temperature 0, writes one JSON line per call, and is resumable. Local runs use Ollama's native
  `/api/chat`, with `num_ctx` set and thinking off. Claude runs go through the Anthropic API, with the model ID
  recorded.
- `score.py` normalises the answers (case, whitespace, list order where order doesn't matter), applies the ±5
  tolerance to proportions, and reports accuracy per cell with a Wilson 95% interval.
- **Sample sizes.** The pilot is 10 structures per type and size, about 1,000 calls per model, enough to find harness
  bugs. The pilot does not test any hypothesis. The confirmatory run uses fresh seeds, 40 structures per cell, and a
  test per hypothesis as above. Seeds are never reused between the pilot and the confirmatory run.
- **The encodings are written by code, not by a model**, so they carry the same facts. A test checks that every
  question's answer is derivable from each encoding's source data.

## Threats
- **The ophanic encoding uses the designer's own conventions.** A model may do worse with Ophanic in general than with
  Daedalus's dialect. Noted, not fixed.
- **Contamination.** Claude has seen Ophanic-like box drawings, and the local model probably has too. The
  comparison is between encodings, so this affects every arm alike.
- **Questions favour spatial readings.** The axes include graph questions, where the prediction is no advantage (H2),
  so the set isn't one-sided.
- **The author is the builder.** Momus reviews this design before any confirmatory data, and the analysis is fixed
  above.

## Outputs
- `results/<run>/calls.jsonl`, where each row holds the task, encoding, question, model, answer, correctness, tokens
  and latency. There is no free text beyond the model's short answer.
- `REPORT.md` per run, reviewed by Momus, which says pilot or confirmatory at the top.

## Amendments informed by the pilot (2026-10-15, before any confirmatory data)

*Everything above this section is the original pre-registration, unchanged. These amendments were written after
the qwen3:8b pilot (`REPORT-pilot.md`) and Momus's review of it
(`.daedalus/momus/trials/2026-10-15-ophanic-perception-pilot.md`, local to the main checkout and not committed). **They were informed by the pilot's
results**, which is why they are recorded separately rather than edited into the hypotheses: a reader can see what
was fixed before any data and what changed after seeing some. No confirmatory data exists yet. The harness does not
implement them yet; this is design text only.*

*Where an amendment needs a choice, the option taken is Momus's recommendation where he gave one, otherwise the
most conservative, and it is marked **proposed — Kohl to confirm**.*

- **A1. Split H1.** Test spatial and proportion separately.
  - **H1a (spatial):** on `layout` `right_of` and `below`, `ophanic` beats `prose` and `list`, with H1's
    10-point threshold at medium size.
  - **H1b (proportion):** the pilot's share question is a lookup for the text arms (they state "35% of the row's
    width") and a character count for ophanic, and the pilot model answered "25" whatever the drawing said, so as
    written H1 could not separate reading from guessing. The proportion question must be fixed. Options: (i) give
    the text arms character widths instead of percentages, so every arm has to compute the share; (ii) ask a
    comparison ("which is wider, X or Y?"); (iii) otherwise keep proportion as a labelled descriptive measure, not
    part of H1. *Chosen: (i), the fix Momus's trial names as what would change his mind; if it can't be built
    cleanly, fall back to (iii). **Proposed — Kohl to confirm.*** Whatever is chosen, the report states the
    constant-guess baseline next to the proportion accuracy.
- **A2. Graph arm.** In the pilot only 29-50% of edges were drawn as arrows, and edge labels sat behind slugs, so
  the ophanic graph arm was a partial-edge list with a picture. Options: (i) draw every edge; (ii) relabel the arm
  "partial-edge list plus picture" and drop H2's claim about drawings. *Chosen: (ii), the conservative one, since
  (i) is a new drawing algorithm whose layout choices would themselves need review. **Proposed — Kohl to
  confirm.*** Separately, fix or replace `no_dependents`, which was wrong in every arm on almost every question:
  rename it "no incoming edge", prevent the looping (a stop sequence or a larger num_predict), and require the
  answer to be a single name or a count so it is not at the floor.
- **A3. Prompt framing.** Add one neutral sentence to every arm saying what the structure is and how to read it
  (for ophanic: boxes are panels or groups, a column's width is its share, slugs are explained in the legend).
  Test a fenced versus an unfenced variant, since Daedalus writes fenced blocks in practice.
- **A4. Name the statistics.** Each hypothesis gets a paired, structure-clustered test: a McNemar test or a
  cluster bootstrap. *Chosen: a cluster bootstrap over structures (resampling structures, keeping each one's arms
  and questions together), because McNemar alone ignores the clustering the pilot's intervals also ignored.
  **Proposed — Kohl to confirm.*** State a power calculation: at n=40 structures per cell the standard error is
  roughly 7-8 points against a 10-point threshold, so a single-cell test is weak. Define H3's "advantage":
  *chosen: ophanic minus the better of `prose` and `list` at each size, with the test being a bootstrap interval
  on (large advantage − small advantage) above zero. **Proposed — Kohl to confirm.***
- **A5. H4 (noise).** Put noise on every arm, or on all ophanic structures, and use an equivalence margin; the
  5-point threshold is not resolvable at n=40 (the pilot's per-arm interval was about ±8 points). *Chosen: noise on
  all ophanic structures (`--noise-every 1`), with a 5-point equivalence margin tested on the cluster-bootstrap
  interval of the paired difference; if that interval is wider than the margin, H4 is reported as unresolved, not
  as passed. **Proposed — Kohl to confirm.***
- **A6. H5 (cost).** Pre-register the tokenizer, compact versus indented json, and per-type reporting. The
  headline is by structure type, not one pooled ratio, and `list` is a second comparator. *Chosen: each model's own
  reported input count (Ollama `prompt_eval_count`, Anthropic `usage.input_tokens`), encoding-only (minus a
  measured bare question prompt, as `measure_tokens.py` does), with compact json as the primary comparator, list
  second, and indented json reported for continuity. **Proposed — Kohl to confirm.***
- **A7. Pre-register the conventions.** Fix the conventions that are not yet fixed (slug indirection, how items
  flow inside a box, how width maps to share) as written in README "How each structure is drawn" at the commit
  that starts the confirmatory run, and say plainly that these are Daedalus's dialect, not Ophanic in general.
- **A8. Confirmatory model.** qwen3:8b with thinking off is near the floor on half the questions, so it will not
  discriminate. Pre-register at least one reasoning-capable or larger model: qwen3:14b, or Claude after
  2026-10-23. *Chosen: qwen3:14b locally (installed, no paid budget), plus Claude when Kohl starts the paid runs
  after 2026-10-23; qwen3:8b stays as a pilot-only model. **Proposed — Kohl to confirm.*** Keep the seed rule:
  fresh seeds, never 1015 or 99001.
- **A9. H6 (construction).** It is not built, so it is marked **not run** here; it is not part of the
  confirmatory run until it is built and reviewed.

Harness implements the proposed options as of f869c22; Kohl's confirmation still pending.

## A10-A13, proposed — Kohl to confirm (from the pilot-2 review)

*Written after pilot 2 (`REPORT-pilot2.md`) and Momus's review of the harness and that pilot
(`.daedalus/momus/trials/2026-10-15-ophanic-perception-pilot2.md`, local to the main checkout), and after the
qwen3:14b floor pilot (`REPORT-pilot3-14b.md`). Like A1-A9 they were informed by pilot data, are recorded
separately from the hypotheses, and are **proposed — Kohl to confirm**. No confirmatory data exists yet.*

- **A10. Decision rules.** These are what score.py already does, written down.
  - *H1a, H1b, H2:* an arm difference "meets" the 10-point threshold when the point estimate is at least 10 points
    **and** the lower bound of its 95% cluster-bootstrap interval is above zero. H1 (a or b) is supported when
    ophanic meets it against both prose and list; H2 is falsified when ophanic meets it against both json and list.
  - *H3:* the slope (large advantage − small advantage, advantage = ophanic minus the better of prose and list)
    "grows" when its interval's lower bound is above zero; it is falsified when the point estimate is below zero;
    otherwise it is "not shown".
  - *H4, three ways:* "holds" when the whole interval of noisy minus clean lies inside ±5 points; "falsified" when
    the whole interval lies at or below −5; otherwise "unresolved".
  - Every test is run per model and thinking condition (see A8 revision); nothing is pooled across conditions.
- **A11. Floor rule.** Before the confirmatory run, a floor pilot (3 structures per cell, fresh seed) is run for
  each confirmatory model and thinking condition. Any question kind that every main arm (ophanic@100, ophanic@60,
  prose, json, list) gets wrong on more than half of that pilot's items is reported descriptively for that
  condition and excluded from the hypothesis it belongs to (H1b for `share`, H2 for `path_length`; `no_incoming`
  belongs to no hypothesis). The exclusions are written here, with the pilot that justified them, before the
  confirmatory data exist.
- **A12. Lookup ceiling for share.** A `list-lookup` control arm on layouts states each column's share as a
  percentage, the pilot-1 list. It is reported next to H1b and is never a comparator in a test: it shows how well
  the model does when no arithmetic is needed, so a text-arm loss on H1b can be read as "dividing" rather than
  "reading". H1b pairs the text arms with ophanic@60, the drawing whose widths they state (ophanic@100 draws the
  same shares at other widths).
- **A13. Matched framing.** Every arm of a structure type gets the same framing sentence: the same description of
  the structure and, for layouts, the same rule for a share (a column's width divided by its row's width), differing
  only in the name of the form and how that form marks things. Pilot 2's separately written sentences
  (`--framing pilot2`) said different things to different arms (the prose sentence never said how to compute a
  share).
- **A8, revised.** Thinking status is part of the model's identity.
  - Local arm: **qwen3:14b with thinking** (`--think`, max-tokens 4096, no blank-line stop).
  - Paid arm: **Claude with thinking on and effort pinned per model** (`EFFORT_PIN` in run.py, medium for Haiku,
    Sonnet and Opus 5.5, recorded in every row), once Kohl starts paid runs after 2026-10-23.
  - qwen3:8b and qwen3:14b without thinking are a separate **no-reasoning condition**, reported on their own and
    never pooled with a thinking model in any test.

Harness implements A10-A13's proposed options, the A8 revision and the Anthropic safeguards as of the commit that
adds this section; Kohl's confirmation still pending.

**Conventions freeze (A7).** To freeze: record the commit hash here when Kohl starts the confirmatory run.
Frozen at: *(not yet frozen)*.
