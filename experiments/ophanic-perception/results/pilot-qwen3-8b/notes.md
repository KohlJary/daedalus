## What the pilot was for, and what it found

The pilot ran qwen3:8b (Ollama 0.12.7, `think: false`, temperature 0, num_ctx 10240, num_predict 128) on seed
1015. That's 10 structures per type and size, 3 questions each, and 5 encodings (ophanic@100, ophanic@60, prose,
json, list), plus ophanic-noise@100 on the even-indexed structures: 1,485 calls in 6.6 minutes. ComfyUI stayed up.

**Harness.**
- No call errored, and none came back empty or over num_ctx.
- Every gold answer is rederived from the json encoding by an independent solver in `test_generate.py`, for the
  test seed and, in `test_pilot_answers_derivable_from_json`, for every pilot question in `tasks/1015.jsonl`. The
  questions every encoding got wrong are listed case by case under "Floors" below. (An earlier line here said
  hand spot-checks of those cases found the gold right; nobody could verify which cases were checked, so it is
  replaced by the test and the list.)
- Bugs found and fixed during the build and the pilot:
  - a test regex that missed chained edges;
  - the token-cost ratio, which wasn't paired: the noise arm covers half the structures;
  - name normalisation, which marked "Archive panel" wrong.

**Model behaviour that affects scoring.**
- 89 answers ran over 200 characters. 67 of them were `no_dependents` answers that loop, repeating node names
  until num_predict cuts them off; most of the rest started reasoning in spite of `think: false`.
- `no_dependents` is near 0% in every encoding.

**Facts about the drawings that matter for interpretation.**
- *Graphs:* most edges aren't drawn. Only edges whose ends share a row with nothing between them get an arrow.
  The rest are listed under the diagram:

  | | small | medium | large |
  |---|---|---|---|
  | edges drawn at width 100 | 50% | 43% | 33% |
  | edges drawn at width 60 | 36% | 29% | 29% |

  The ophanic graph arm is therefore largely a list with a picture on top.
- *Width 60:* it wraps graphs into 1.6–2.7 bands. It abbreviated only 6 layout labels across 30 layouts.

**Descriptive only.** None of these numbers tests a hypothesis.

## Read this before quoting any number

Every result here is about **qwen3:8b with thinking off**, reading **raw, unframed text**: the prompt is the
encoding, the question and "Answer with only the answer.", with no fence and no word on what a box diagram is or
how to read widths and slugs. There are **10 structures per type and size**, each asked three questions, and the
**intervals ignore that clustering** and the pairing of arms. Within those limits, what the checks below show:

- **Containment:** a real gap for this model. Ophanic is below every text arm, and the paired table is lopsided
  against it. This is the structure being tested (side-by-side sibling groups interleave when read line by line),
  not a drawing bug, and it shouldn't be explained away as dialect.
- **Layout:** on the spatial questions ophanic ties the text arms. The whole layout deficit is the proportion
  question, where the text arms are handed the number and ophanic has to count characters. The model mostly
  answers 25, and its share accuracy is no better than always guessing 25. That is a model/tokenizer limit: the
  drawn widths are accurate.
- **Graphs:** the arms look level because the questions are at the floor, not because the encodings are at
  parity, and most edges in the ophanic graphs aren't drawn anyway. The graph arm tests nothing about drawings.
- **Noise:** no detectable cost, at a resolution (±8 points) that can't decide H4.
- **Cost:** by structure type, not one number. Ophanic is close to json on layout and far above it on
  containment, and further still above compact json and the list.
- It says little about Claude, which is what reads these diagrams in practice.

## What this says about edict 0017

This pilot says almost nothing about whether Ophanic should be Daedalus's default spatial language. What it does
show, for qwen3:8b without reasoning reading raw box text: a large, real containment deficit on paired calls; that
the model can't turn character widths into percentages; and that the token overhead is real in some structure
types, from about json's cost on layouts up to several times compact json or the list on containment. What it does
not show: anything about Claude, which is who reads these diagrams in practice and is stronger on spatial text and
reasoning; anything about fenced blocks with the legend and notes Daedalus actually writes; that diagrams are worse
at spatial layout questions, which tied the text arms; or anything about graphs, which sat at the floor. So it
neither supports nor undermines the edict. Its useful signal is a prior: containment-style diagrams, and any
proportion that has to be measured from character widths, should be backed by text (a list, or stated numbers).
Whether Ophanic helps Claude stays untested until the confirmatory run, which can't start before 2026-10-23.
