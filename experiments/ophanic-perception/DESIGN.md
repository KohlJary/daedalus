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
