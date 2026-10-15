# Ophanic perception experiment: harness

The design and pre-registration are in [DESIGN.md](DESIGN.md). This folder is the harness that runs it. Python 3.11+,
standard library only (pytest for the tests).

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
python generate.py --seed 1015 --per-cell 10        # writes tasks/1015.jsonl
python -m pytest test_generate.py -q
```

Each line of `tasks/<seed>.jsonl` is one structure: its type (`layout`, `graph`, `containment`), size (`small`,
`medium`, `large`), the generator's `data`, seven encodings (`ophanic@100`, `ophanic@60`, `ophanic-noise@100`,
`ophanic-noise@60`, `prose`, `json`, `list`) and three questions, one per question kind for its type:

| Type | Questions (kind) |
|---|---|
| layout | right_of (spatial), below (spatial), share (proportion, ±5) |
| graph | reach (path), path_length (path), no_dependents (aggregate) |
| containment | inside (containment), holders (containment), count (count) |

Generation is deterministic: each structure draws from `random.Random("<seed>:<type>:<size>:<i>")`. Generation
fails loudly (`HarnessBug`) if a clean diagram fails the lint, a row isn't the diagram's width, or a noise variant
doesn't lint as exactly one width and one joins problem. The tasks files aren't committed: regenerate them.
`tasks/1015.jsonl` (the pilot) has sha256 `ebe363660187bccd6749bcfd999efa8a0977ab2bd5424cf34a5ae7f33a39524a`.

**Seeds.** The pilot used 1015 and the tests use 99001. A confirmatory run must use fresh seeds, never these.

### How each structure is drawn

- **Layout:** nested rows and columns in the shared-divider style of `docs/design/tui/*.oph`. A column's share of
  its row is its border-to-border width over the row's. A label that doesn't fit is cut with `…` and named in a
  `note:` line under the diagram.
- **Graph:** layered left to right by longest path. Each node is a box, and an edge is drawn as `─█Rnn─▶` when its
  two ends share a row with nothing between them. Its slug has a legend line giving the edge's label. Slugs number
  the drawn edges per diagram in ascending edge order. Every other edge is listed under the diagram as
  `note: A ─▶ B (label)`. When the layers don't fit the width, they wrap into bands separated by a `├──┤` divider,
  and edges between bands become listed edges.
- **Containment:** each group is a box with a title row, a divider, and its items. Subgroups are boxes inside it.
  An item held by two groups is drawn in both. Everything sits inside a frame, so every row has the same width.
- **Noise:** one ragged row (a space before the row's last character) and one broken join (an inner `│` replaced by
  a space). Only box characters and spaces change.

## 2. Run

```bash
# Local (Ollama native /api/chat, think off, temperature 0, one num_ctx for the whole run)
python run.py --tasks tasks/1015.jsonl --run pilot-qwen3-8b --model qwen3:8b --num-ctx 10240
python run.py ... --dry-run            # show the plan and num_ctx only
```

- `--encodings` defaults to `ophanic@100,ophanic@60,prose,json,list`. `--noise-every 2` adds `ophanic-noise@100`
  for every other structure (index 0, 2, 4...), which is what the pilot ran. Use `--noise-every 1` for all of them.
- `--num-ctx 0` (the default) picks one from the largest prompt at one token per character. That's very
  conservative: the largest pilot prompt, 9,548 characters, was 2,461 tokens. Set it explicitly to save VRAM.
- Reruns skip calls already recorded without an error, so a run resumes where it stopped.
- Every row records the task, encoding, question, gold, answer, correctness, `prompt_eval_count` and
  `eval_count` from the API, the latency, and num_ctx.

**Paid runs.** `--backend anthropic` calls the Messages API with `--model` as the model ID. It refuses to start
unless `OPX_ALLOW_PAID=1` is set. Kohl starts paid runs; there are none before 2026-10-23.

**GPU.** qwen3:8b at num_ctx 10240 fits on the 16 GB card alongside ComfyUI. If Ollama fails to load a bigger model,
stop ComfyUI with `systemctl --user stop comfyui` and start it again afterwards. Run `ollama stop <model>` when
done.

## 3. Score

```bash
python measure_tokens.py --tasks tasks/1015.jsonl --run pilot-qwen3-8b --model qwen3:8b   # once, for the cost table
python score.py results/pilot-qwen3-8b --report REPORT-pilot.md --label PILOT --notes results/pilot-qwen3-8b/notes.md
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
