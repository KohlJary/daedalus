# Ophanic perception experiment: harness

The design and pre-registration are in [DESIGN.md](DESIGN.md). This folder is the harness that runs it. Python 3.11+,
standard library only (pytest for the tests).

**Harness 3.** The harness implements the options DESIGN.md's pilot-informed amendments (A1-A13, and A8 as
revised) propose, as the default for the next run. Those amendments are **proposed, Kohl to confirm**; until then
harness 3 is what a confirmatory run *would* use. `--harness 1 --framing off --noise-every 2` reproduces pilot 1,
and `--harness 2 --framing pilot2` pilot 2.

## Runbook for the confirmatory run (after Kohl confirms the amendments)

1. **Claude smoke test, first, by Kohl after 2026-10-23.** Nine calls on Haiku, a few cents, to check that the
   untested raw-HTTP client parses real responses and that answers are not empty at the chosen max_tokens:
   ```bash
   python generate.py --seed <fresh, non-reserved> --per-cell 1
   OPX_ALLOW_PAID=1 python run.py --tasks tasks/<seed>.jsonl --run smoke-haiku --model claude-haiku-5-5 \
       --backend anthropic --encodings ophanic@100 --noise-every 0 --limit 9
   ```
   Every row should have a non-empty answer, `done_reason` `end_turn` or `stop_sequence`, `effort` `medium`, and no
   error. Nothing else in this runbook runs before this passes.
2. A floor pilot (A11) per confirmatory model and thinking condition: 3 structures per cell, a fresh seed outside
   the reserved range. Record any excluded question kinds in DESIGN.md.
3. Freeze the conventions (A7): record the commit hash in DESIGN.md.
4. Generate the confirmatory tasks from a seed in 2000–2999, 40 structures per cell, and run each condition.
5. `score.py` per run, labelled CONFIRMATORY; Momus reviews the report before anyone reads it as a result.

| Amendment | Where | What the harness does |
|---|---|---|
| A1 split H1 | generate.py, score.py | Text arms state character widths ("Queue: 35 of 59 characters"), never a percentage, so every arm computes the share; score.py tests H1a (spatial) and H1b (proportion) apart, with the constant-guess baseline |
| A2 graph arm | generate.py, run.py, score.py | Reports call the ophanic graph arm a "partial-edge list plus picture"; `no_dependents` is replaced by "how many nodes have no incoming edge" (one number); a blank-line stop sequence and num_predict 256 |
| A3 framing | generate.py, run.py | One neutral sentence per arm and type (`FRAMING`); `+fenced` arms and `--fenced` for a fenced ophanic variant; `+unframed` arms and `--framing off` |
| A4 statistics | score.py | Cluster bootstrap over structures for every paired arm difference; H3 as a slope against the better of prose and list; power note below |
| A5 noise | run.py, score.py | `--noise-every 1` (all structures) by default; H4 read against a ±5-point equivalence margin |
| A6 cost | measure_tokens.py, score.py | Every arm's unframed prompt measured with the model's own count; H5 encoding-only, by type, against compact json, then list, then indented json |
| A7 conventions | this README | "Conventions" below |
| A8 model (revised) | run.py, score.py | `--model` with `--backend ollama` (qwen3:14b `--think` as the local arm) or `--backend anthropic` (Claude, behind `OPX_ALLOW_PAID=1`, effort pinned); thinking status is part of the condition, and score.py reports and tests each condition on its own |
| A9 H6 | score.py | Reported as **not run** |
| A10 decision rules | score.py | Estimate ≥ 10 and lower bound > 0; H3 grows / falsified / not shown; H4 holds / falsified / unresolved |
| A11 floor rule | score.py | The Floors table gives each question's all-arms-wrong rate per condition |
| A12 lookup ceiling | generate.py, score.py | `list-lookup` arm on layouts (share stated as a percentage), reported next to H1b; H1b pairs the text arms with ophanic@60, whose widths they state |
| A13 matched framing | generate.py, run.py | `--framing matched` (default): one sentence per structure type, the same for every arm but for the form's name and marks |

| File | What it does |
|---|---|
| `generate.py` | Makes the tasks from a seed: structures, their encodings, questions and gold answers |
| `run.py` | Sends each (structure, encoding, question) to a model; writes `results/<run>/calls.jsonl` |
| `score.py` | Rescores a run and writes its report |
| `measure_tokens.py` | Measures the prompt tokens of compact json and of the bare question, for the cost table (`results/<run>/tokens.jsonl`) |
| `power.py` | Power of the decision rules at the confirmatory size, by simulation from a pilot's per-structure differences |
| `test_generate.py` | Harness tests: determinism, lint, answers derivable from the json, the encodings carry the same facts, scoring |
| `oph_lint.py` | The Ophanic lint (`daedalus oph check`), copied verbatim from `daedalus-oph` at b28ca53 |

## 1. Generate

```bash
python generate.py --seed 5016 --per-cell 3                    # harness 2 (default): writes tasks/5016.jsonl
python generate.py --seed 1015 --per-cell 10 --harness 1       # the pilot's tasks, byte for byte
python -m pytest test_generate.py -q
```

Each line of `tasks/<seed>.jsonl` is one structure: its type (`layout`, `graph`, `containment`), size (`small`,
`medium`, `large`), the generator's `data`, its encodings (`ophanic@100`, `ophanic@60`, `ophanic-noise@100`,
`ophanic-noise@60`, `prose`, `json`, `list`, and from harness 2 `json-compact`) and three questions, one per
question kind for its type:

| Type | Questions (kind) |
|---|---|
| layout | right_of (spatial), below (spatial), share (proportion, ±5) |
| graph | reach (path), path_length (path), no_incoming (aggregate; harness 1: no_dependents) |
| containment | inside (containment), holders (containment), count (count) |

Harness 1 and 2 draw the same structures and the same diagrams from a seed; only the layout text arms (widths
instead of percentages), the graph's aggregate question, and `json-compact` differ. A test checks both.

Generation is deterministic: each structure draws from `random.Random("<seed>:<type>:<size>:<i>")`. Generation
fails loudly (`HarnessBug`) if a clean diagram fails the lint, a row isn't the diagram's width, or a noise variant
doesn't lint as exactly one width and one joins problem. The tasks files aren't committed: regenerate them.
`tasks/1015.jsonl` (the pilot) has sha256 `ebe363660187bccd6749bcfd999efa8a0977ab2bd5424cf34a5ae7f33a39524a`.
`tasks/5016.jsonl` (pilot 2: `--seed 5016 --per-cell 3`, harness 2) has sha256 `185e2651b8cc6726d736b87c4c8a8c0b85bfd24199882dd31ef089dbc68ac4d9`.

**Seeds.** Never reuse a seed between a pilot and a confirmatory run.

| Seed | Use |
|---|---|
| 1015 | pilot 1 (harness 1) |
| 5016 | pilot 2 (harness 2) |
| 7117 | pilot 3, the qwen3:14b floor pilot (harness 3) |
| 99001 | the tests |
| **2000–2999** | **reserved for confirmatory runs.** No pilot or test uses them; generate.py prints a note when one is generated |

### How each structure is drawn

These are **Daedalus's dialect** of Ophanic (edict 0017's conventions as built here), not Ophanic in general. A7
pre-registers them as written here at the commit that starts the confirmatory run.

- **Layout:** nested rows and columns in the shared-divider style of `docs/design/tui/*.oph`.
  - *Width to share:* a column's share of its row is its border-to-border width (from its left divider to its right
    divider) over the row's border-to-border width. At width 100 a row spans 99 characters, at width 60, 59. Drawn
    shares are within 2.5 points of the nominal share for every share question.
  - In harness 2 the text arms state the 60-column drawing's widths exactly ("Queue: 35 of 59 characters";
    `"width"` in json), so the ophanic@60 arm and the text arms carry identical numbers and every arm divides.
    Because a row is 59 wide, never 100, a stated width is never itself within 5 points of the share.
  - A label that doesn't fit is cut with `…` and named in a `note:` line under the diagram.
- **Graph:** layered left to right by longest path. Each node is a box, and an edge is drawn as `─█Rnn─▶` when its
  two ends share a row with nothing between them. Every other edge is listed under the diagram as
  `note: A ─▶ B (label)`. When the layers don't fit the width, they wrap into bands separated by a `├──┤` divider,
  and edges between bands become listed edges. In the pilot only 29–50% of edges were drawn, so reports call this
  arm a **partial-edge list plus picture** (A2), and H2 says nothing about drawings.
  - *Slug indirection:* a drawn edge carries a slug, not its label. Slugs number the drawn edges per diagram in
    ascending edge order (`█R01`, `█R02`...), and a legend line under the diagram (`█R01: calls`) gives each one's
    label. Listed edges carry their label inline.
- **Containment:** each group is a box with a title row, a divider, and its items. Subgroups are boxes inside it,
  after the group's own items. An item held by two groups is drawn in both. Top-level groups sit side by side, as
  many per row as fit, and further rows of groups follow below a blank line. Everything sits inside a frame, so
  every row has the same width.
  - *Item flow:* a group's items flow left to right in their data order, two spaces apart, wrapping to a new line
    when the next item would pass the box's inner width; so a line may hold one item or several.
- **Noise:** one ragged row (a space before the row's last character) and one broken join (an inner `│` replaced by
  a space). Only box characters and spaces change.

## 2. Run

```bash
# Local (Ollama native /api/chat, think off, temperature 0, one num_ctx for the whole run)
python run.py --tasks tasks/5016.jsonl --run pilot2-qwen3-8b --model qwen3:8b --num-ctx 6144 \
    --encodings ophanic@100,ophanic@100+fenced,ophanic@100+unframed,prose,json,list
python run.py ... --dry-run            # show the plan and num_ctx only
# The pilot, as it ran
python run.py --tasks tasks/1015.jsonl --run pilot-qwen3-8b --model qwen3:8b --num-ctx 10240 \
    --framing off --noise-every 2 --max-tokens 128 --stop ''
```

- `--encodings` defaults to `ophanic@100,ophanic@60,prose,json,list`. An arm may carry modifiers: `+fenced` wraps
  an ophanic diagram in a ``` fence (as Daedalus writes them); `+unframed` drops that arm's framing sentence.
  `--fenced` adds `+fenced` to every ophanic arm.
- `--noise-every 1` (the default, A5) adds the noise arm for every structure; `--noise-every 2` for every other
  one, as the pilot ran. The noise arm takes the modifiers of the first `ophanic@100` arm, which it is paired with.
- `--framing matched` (the default, A3 and A13) starts every prompt with one neutral sentence saying what the
  structure is and how to read it, the same sentence for every arm of a structure type except for the form's name
  and how it marks things (`MATCHED_*` in generate.py). `--framing pilot2` gives pilot 2's separately written
  sentences, `--framing off` the unframed prompt. Tests check that no sentence names an element or states a number.
- `list-lookup` (harness 3, layouts only) is the lookup-ceiling control (A12): the list with each share stated as a
  percentage. Add it to `--encodings`; it is skipped for graphs and containment.
- `--max-tokens` (default 256 for Ollama) and `--stop` (default a blank line) keep answers short without cutting
  off a real one (A2); each row records `done_reason`, and the report counts answers cut off by the limit. The stop
  also cuts a reasoning preamble after its first paragraph, which is then scored wrong.
- **No answer is never a wrong answer.** A call that comes back empty, or cut off by the token limit while
  thinking (Claude, or Ollama with `--think`), is retried (`--retries 2`), then recorded as an error and left out of
  scoring; a rerun retries it. At temperature 0 an Ollama retry repeats itself, so use `--retries 0` there.
- `--num-ctx 0` (the default) picks one from the largest prompt at one token per character. That's very
  conservative: the largest pilot prompt, 9,548 characters, was 2,461 tokens. Set it explicitly to save VRAM.
- Reruns skip calls already recorded without an error, so a run resumes where it stopped.
- Every row records the task, encoding, question, gold, answer, correctness, `prompt_eval_count` and
  `eval_count` from the API, the latency, and num_ctx.

**Models (A8).** The model is `--model`; nothing in the harness assumes qwen3:8b.
- qwen3:8b was the pilots' model and stays pilot-only.
- qwen3:14b with thinking (`--think --max-tokens 4096 --stop '' --retries 0`) is the proposed confirmatory local
  arm (A8 revised); qwen3:8b and qwen3:14b without thinking form a separate no-reasoning condition. Thinking calls
  run about 20 s each on the 16 GB card, and a share question on the ophanic arm can run to the 4096-token limit.
  It needs ComfyUI stopped (below).
- Claude: `--backend anthropic --model claude-haiku-5-5` (or `claude-sonnet-5-5`, `claude-opus-5-5`). Thinking is
  on (it can't be turned off on Opus 5.5) and shares max_tokens, so the default is 4096 and less than 2048 is
  refused. Effort is pinned per model in `EFFORT_PIN` (medium for all three, proposed) and recorded in every row;
  `--effort` overrides it and is recorded as a departure. A model with no pinned effort is refused. A
  whitespace-only stop is applied to the answer client-side. The raw-HTTP client is untested against the live API
  until the smoke test (runbook step 1).
- **Claude runs are not deterministic.** Current models reject `temperature`, so none is sent, and each call is one
  sample: a rerun of the same prompt can give a different answer. Ollama runs are deterministic (temperature 0,
  seed 0). Score Claude runs as one sample per call, and don't compare a rerun call by call.

**Paid runs.** `--backend anthropic` (in run.py and measure_tokens.py) refuses to start unless `OPX_ALLOW_PAID=1`
is set. Kohl starts paid runs; there are none before 2026-10-23.

**GPU.** qwen3:8b at num_ctx 10240 fits on the 16 GB card alongside ComfyUI. If Ollama fails to load a bigger model,
stop ComfyUI with `systemctl --user stop comfyui` and start it again afterwards. Run `ollama stop <model>` when
done.

## 3. Score

```bash
python measure_tokens.py --tasks tasks/5016.jsonl --run pilot2-qwen3-8b --model qwen3:8b --num-ctx 6144   # cost table
python score.py results/pilot2-qwen3-8b --report REPORT-pilot2.md --label "PILOT 2" --notes results/pilot2-qwen3-8b/notes.md
# Several runs into one report, one section per model and thinking condition (never pooled)
python score.py results/pilot3-qwen3-14b results/pilot3-qwen3-14b-think --report REPORT-pilot3-14b.md --label "PILOT 3"
# The pilot's run measured json-compact only: --variants json-compact
```

Answers are normalised before scoring: think blocks, markdown and quotes are stripped, case and whitespace are
folded, and trailing punctuation is dropped. Then:

- a name answer must match the gold name exactly;
- a yes/no answer is judged on its first word;
- a number answer is judged on the first number in it;
- a proportion is correct within ±5 points;
- a set answer is split on commas, semicolons, newlines and "and", then compared as a set.

Each cell reports its accuracy, the Wilson 95% interval and n. The report also gives the mean input tokens per
encoding and their ratio to `json`.

**Hypotheses (A4).** The report opens with the pre-registered statistics: every paired arm difference with a
percentile 95% interval from a cluster bootstrap over structures (`--boot 2000` replicates, `--boot-seed 0`,
resampling structures within each type × size cell and keeping each structure's arms and questions together);
H1a and H1b (H1b pairs the text arms with ophanic@60, and shows the lookup ceiling); H2 against json and list; H3
as (large − small) of ophanic minus the better of prose and list; H4 against ±5 points; H5 by type; H6 not run.
The decision rules are DESIGN.md's A10. `--primary` names the ophanic arm tested (default `ophanic@100`). A run
labelled PILOT prints no readings against the thresholds. Each model and thinking condition gets its own section
and its own tests; pairs never cross conditions. At 3 structures per stratum (the pilots) the percentile
bootstrap has about ten distinct resamples per cell and its intervals are too narrow: don't read them.

**Power** (`python power.py`, by simulation). For each test, power.py takes pilot 1's per-structure paired
differences (qwen3:8b without thinking, 10 structures per cell), centres them, shifts them by a true difference,
resamples the number of structures the confirmatory test has (40 per cell), and applies A10's rule (estimate ≥ 10
and lower bound > 0; for H4, the interval inside ±5), 4,000 times per row, seed 0:

| Test | Structures | Per-structure SD | SE | Power at a true difference of 10 / 15 / 20 / 25 points | False "meets" at 0 |
|---|---|---|---|---|---|
| H1a (layout spatial, medium; vs prose) | 40 | 40 points | 6.4 | 0.36 / 0.68 / 0.89 / 0.98 | 0.03 |
| H2 (graph path, all sizes; vs json) | 120 | 37 points | 3.4 | 0.52 / 0.94 / 1.00 / 1.00 | 0.00 |

**Minimum detectable effect** (80% power) under A10's rule: about **17–18 points** for H1a and about **13 points** for
H2. A true 10-point advantage, the threshold itself, is detected about a third of the time for H1a and half the
time for H2: the rule asks the estimate to clear 10, so at a true 10 it is close to a coin flip before the interval
condition. H1 needs to beat both prose and list, which lowers its power further. For H4, at 360 structures and
pilot 1's noise variance (only 2 of 135 pairs flipped), the interval is about ±0.8 points: a true difference of 0 or
−2 points "holds" with probability 1.00, and a true −5 with 0.04. These numbers rest on one weak model's variance;
a model nearer the ceiling, or a thinking model, will have a different per-structure SD, so rerun `power.py` on
its floor pilot.
