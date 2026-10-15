# Ophanic perception experiment: harness

The design and pre-registration are in [DESIGN.md](DESIGN.md). This folder is the harness that runs it. Python 3.11+,
standard library only (pytest for the tests).

**Harness 2.** The harness implements the options DESIGN.md's pilot-informed amendments (A1-A9) propose, as the
default for the next run. Those amendments are **proposed, Kohl to confirm**; until then harness 2 is what a
confirmatory run *would* use, and `--harness 1` / `--framing off` / `--noise-every 2` reproduce the pilot.

| Amendment | Where | What the harness does |
|---|---|---|
| A1 split H1 | generate.py, score.py | Text arms state character widths ("Queue: 35 of 59 characters"), never a percentage, so every arm computes the share; score.py tests H1a (spatial) and H1b (proportion) apart, with the constant-guess baseline |
| A2 graph arm | generate.py, run.py, score.py | Reports call the ophanic graph arm a "partial-edge list plus picture"; `no_dependents` is replaced by "how many nodes have no incoming edge" (one number); a blank-line stop sequence and num_predict 256 |
| A3 framing | generate.py, run.py | One neutral sentence per arm and type (`FRAMING`); `+fenced` arms and `--fenced` for a fenced ophanic variant; `+unframed` arms and `--framing off` |
| A4 statistics | score.py | Cluster bootstrap over structures for every paired arm difference; H3 as a slope against the better of prose and list; power note below |
| A5 noise | run.py, score.py | `--noise-every 1` (all structures) by default; H4 read against a ±5-point equivalence margin |
| A6 cost | measure_tokens.py, score.py | Every arm's unframed prompt measured with the model's own count; H5 encoding-only, by type, against compact json, then list, then indented json |
| A7 conventions | this README | "Conventions" below |
| A8 model | run.py, measure_tokens.py | `--model` with `--backend ollama` (qwen3:8b, qwen3:14b) or `--backend anthropic` (Claude, behind `OPX_ALLOW_PAID=1`) |
| A9 H6 | score.py | Reported as **not run** |

| File | What it does |
|---|---|
| `generate.py` | Makes the tasks from a seed: structures, their encodings, questions and gold answers |
| `run.py` | Sends each (structure, encoding, question) to a model; writes `results/<run>/calls.jsonl` |
| `score.py` | Rescores a run and writes its report |
| `measure_tokens.py` | Measures the prompt tokens of compact json and of the bare question, for the cost table (`results/<run>/tokens.jsonl`) |
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

**Seeds.** Never reuse a seed between a pilot and a confirmatory run.

| Seed | Use |
|---|---|
| 1015 | pilot 1 (harness 1) |
| 5016 | pilot 2 (harness 2) |
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
- `--framing on` (the default, A3) starts every prompt with one neutral sentence saying what the structure is and
  how to read it (`FRAMING` in generate.py; a test checks it names nothing and states no number).
- `--max-tokens 256` and `--stop` (default a blank line) keep answers short without cutting off a real one (A2);
  each row records `done_reason`, and the report counts answers cut off by the limit.
- `--num-ctx 0` (the default) picks one from the largest prompt at one token per character. That's very
  conservative: the largest pilot prompt, 9,548 characters, was 2,461 tokens. Set it explicitly to save VRAM.
- Reruns skip calls already recorded without an error, so a run resumes where it stopped.
- Every row records the task, encoding, question, gold, answer, correctness, `prompt_eval_count` and
  `eval_count` from the API, the latency, and num_ctx.

**Models (A8).** The model is `--model`; nothing in the harness assumes qwen3:8b.
- qwen3:8b was the pilots' model and stays pilot-only.
- qwen3:14b (installed, 9.3 GB) is the proposed confirmatory local model. It may need ComfyUI stopped (below).
  `--think` lets it reason; give it `--max-tokens 4096` or more and `--stop ''` if so.
- Claude: `--backend anthropic --model claude-haiku-5-5` (or `claude-sonnet-5-5`, `claude-opus-5-5`). Current
  models reject `temperature` and can't turn thinking off, so the harness sends no temperature unless
  `--temperature` is given, `--effort` sets `output_config.effort`, and `--max-tokens` should leave room for
  thinking (say 4096). A whitespace-only stop is applied to the answer client-side. The raw-HTTP client is
  untested against the live API until the first paid run.

**Paid runs.** `--backend anthropic` (in run.py and measure_tokens.py) refuses to start unless `OPX_ALLOW_PAID=1`
is set. Kohl starts paid runs; there are none before 2026-10-23.

**GPU.** qwen3:8b at num_ctx 10240 fits on the 16 GB card alongside ComfyUI. If Ollama fails to load a bigger model,
stop ComfyUI with `systemctl --user stop comfyui` and start it again afterwards. Run `ollama stop <model>` when
done.

## 3. Score

```bash
python measure_tokens.py --tasks tasks/5016.jsonl --run pilot2-qwen3-8b --model qwen3:8b --num-ctx 6144   # cost table
python score.py results/pilot2-qwen3-8b --report REPORT-pilot2.md --label "PILOT 2" --notes results/pilot2-qwen3-8b/notes.md
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
resampling structures within each type × size cell and keeping each structure's arms, questions and models
together); H1a and H1b; H2 against json and list; H3 as (large − small) of ophanic minus the better of prose and
list; H4 against ±5 points; H5 by type; H6 not run. `--primary` names the ophanic arm tested (default
`ophanic@100`). A run labelled PILOT prints no readings against the thresholds.

**Power.** The cluster is the structure, so precision comes from structures, not calls. At 40 structures per cell
a single-cell accuracy has a standard error of about 7–8 points, against H1's 10-point threshold. A paired
difference is usually tighter, because both arms answer the same questions and most pairs agree; how much
tighter depends on how often the arms disagree. As a rough guide: with a standard error of 7.5 points, a true
10-point difference gets an interval excluding zero only about a quarter of the time; 80% power for a 10-point
effect needs a standard error near 3.5 points, about four times the structures, or the pooling over models and
question kinds that H1 already does. The pilot-2 report gives the bootstrap intervals at its size, which scale
by roughly √(its structures / the confirmatory run's) to estimate the confirmatory precision.
