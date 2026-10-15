# PILOT: no hypothesis tested

**PILOT.** This run exists to find harness bugs. Its numbers are descriptive only and test none of DESIGN.md's hypotheses; the confirmatory run uses fresh seeds and 40 structures per cell.

- Run: `pilot-qwen3-8b`; model(s): qwen3:8b; tasks: 1015.jsonl
- Calls scored: 1485; num_ctx: [10240]
- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±5 points.
- Each structure × size cell has 10 structures, each asked 3 questions. The intervals treat every call as independent: they ignore that a structure's three questions are correlated and that the arms are paired on the same structures, so they are too narrow.
- Overall and per-structure percentages mix questions at the floor (see Floors) with questions near the ceiling.

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

## Checks from the pilot review

Computed by score.py from calls.jsonl (and tokens.jsonl for the cost table), at Momus's request. Like everything else here, these are descriptive.

### Layout: spatial questions versus the proportion question

Spatial is `right_of` plus `below`; proportion is `share`. In the prose, json and list encodings the share is written down as a number, so for them the question is a lookup; in the ophanic encodings it has to be measured from character widths.

| encoding | layout spatial | layout proportion |
|---|---|---|
| ophanic@100 | 29/60 = 48% (36–61) | 14/30 = 47% (30–64) |
| ophanic@60 | 27/60 = 45% (33–58) | 14/30 = 47% (30–64) |
| ophanic-noise@100 | 13/30 = 43% (27–61) | 8/15 = 53% (30–75) |
| prose | 30/60 = 50% (38–62) | 30/30 = 100% (89–100) |
| json | 34/60 = 57% (44–68) | 29/30 = 97% (83–99) |
| list | 31/60 = 52% (39–64) | 30/30 = 100% (89–100) |

On the spatial questions ophanic@100 got 29/60 and the text arms 30–34/60: no gap at this sample size. The layout deficit in the tables below comes from the proportion question.

### Proportion answers: the "25" default and a constant-guess baseline

| encoding | share calls | answered exactly 25 | mean absolute error (points) | accuracy |
|---|---|---|---|---|
| ophanic@100 | 30 | 18 | 12.2 | 14/30 = 47% (30–64) |
| ophanic@60 | 30 | 15 | 11.1 | 14/30 = 47% (30–64) |
| ophanic-noise@100 | 15 | 11 | 15.1 | 8/15 = 53% (30–75) |
| prose | 30 | 3 | 0.0 | 30/30 = 100% (89–100) |
| json | 30 | 3 | 0.3 | 29/30 = 97% (83–99) |
| list | 30 | 3 | 0.0 | 30/30 = 100% (89–100) |

Gold shares over the 30 share questions: 20 ×11, 25 ×3, 30 ×3, 35 ×4, 40 ×1, 45 ×3, 55 ×3, 70 ×1, 75 ×1.
Always answering 25 would score 17/30 = 57% under the ±5 rule; no other constant does better. An ophanic share accuracy at or below that is indistinguishable from a guess, and is no evidence that the model reads widths.

### Floors: questions every arm got wrong

A question counts here when all of ophanic@100, ophanic@60, prose, json, list answered it wrong.

| structure | question | wrong in every arm |
|---|---|---|
| layout | below | 13 of 30 |
| layout | right_of | 2 of 30 |
| layout | share | 0 of 30 |
| graph | no_dependents | 28 of 30 |
| graph | path_length | 16 of 30 |
| graph | reach | 1 of 30 |
| containment | count | 10 of 30 |
| containment | holders | 5 of 30 |
| containment | inside | 0 of 30 |

On graphs the arms look level because the graph questions are near the floor, not because the encodings are at parity: `no_dependents` was wrong in every arm on 28 of 30; `path_length` was wrong in every arm on 16 of 30; `reach` was wrong in every arm on 1 of 30.

<details><summary>The cases (structure, question, gold)</summary>

| structure | question | task | id | gold |
|---|---|---|---|---|
| containment | count | 1015-containment-large-00 | q2 | 8 |
| containment | count | 1015-containment-large-01 | q2 | 10 |
| containment | count | 1015-containment-large-02 | q2 | 8 |
| containment | count | 1015-containment-large-04 | q2 | 10 |
| containment | count | 1015-containment-large-06 | q2 | 9 |
| containment | count | 1015-containment-large-07 | q2 | 14 |
| containment | count | 1015-containment-large-08 | q2 | 6 |
| containment | count | 1015-containment-large-09 | q2 | 8 |
| containment | count | 1015-containment-medium-03 | q2 | 5 |
| containment | count | 1015-containment-medium-08 | q2 | 7 |
| containment | holders | 1015-containment-large-00 | q1 | Birch, Lyra |
| containment | holders | 1015-containment-large-02 | q1 | Apex, Willow |
| containment | holders | 1015-containment-large-04 | q1 | Falcon, Harbor |
| containment | holders | 1015-containment-large-06 | q1 | Heron, Willow |
| containment | holders | 1015-containment-large-09 | q1 | Lyra, Willow |
| graph | no_dependents | 1015-graph-large-00 | q2 | Embedder, Gateway, Mailer, Mirror, Planner, Profile, Resolver, Trainer, Webhook |
| graph | no_dependents | 1015-graph-large-01 | q2 | Compactor, Gateway, Linter, Loader, Sampler, Splitter, Trainer |
| graph | no_dependents | 1015-graph-large-02 | q2 | Compactor, Decoder, Embedder, Monitor, Resolver, Scheduler, Store, Sync |
| graph | no_dependents | 1015-graph-large-03 | q2 | Crawler, Embedder, Logger, Metrics, Parser, Profile, Router |
| graph | no_dependents | 1015-graph-large-04 | q2 | Indexer, Keyring, Linter, Metrics, Monitor, Parser, Upload, Webhook |
| graph | no_dependents | 1015-graph-large-05 | q2 | Compactor, Crawler, Decoder, Lexer, Monitor, Profile, Splitter, Tracer, Upload, Vault, Worker |
| graph | no_dependents | 1015-graph-large-06 | q2 | Billing, Cleaner, Ingest, Loader, Mailer, Metrics, Packer, Policy, Replica, Sampler, Scheduler |
| graph | no_dependents | 1015-graph-large-07 | q2 | Backup, Compactor, Importer, Monitor |
| graph | no_dependents | 1015-graph-large-08 | q2 | Builder, Packer, Search, Tester, Tracer |
| graph | no_dependents | 1015-graph-large-09 | q2 | Crawler, Fetcher, Ingest, Keyring, Ledger, Sampler, Search, Tracer |
| graph | no_dependents | 1015-graph-medium-00 | q2 | Audit, Backup, Billing, Decoder |
| graph | no_dependents | 1015-graph-medium-01 | q2 | Auth, Cron, Exporter, Joiner, Planner |
| graph | no_dependents | 1015-graph-medium-02 | q2 | Audit, Embedder, Gateway, Importer, Metrics, Proxy, Shard, Vault |
| graph | no_dependents | 1015-graph-medium-03 | q2 | Proxy, Secrets, Tester |
| graph | no_dependents | 1015-graph-medium-04 | q2 | Config, Ingest, Keyring |
| graph | no_dependents | 1015-graph-medium-05 | q2 | Cron, Gateway, Metrics, Reports, Scheduler, Search |
| graph | no_dependents | 1015-graph-medium-06 | q2 | Ingest, Notifier |
| graph | no_dependents | 1015-graph-medium-07 | q2 | Cleaner, Ingest, Sampler, Splitter, Worker |
| graph | no_dependents | 1015-graph-medium-08 | q2 | Audit, Decoder, Logger, Policy, Proxy, Search, Upload |
| graph | no_dependents | 1015-graph-medium-09 | q2 | Fetcher, Linter, Logger, Mirror, Resolver, Secrets |
| graph | no_dependents | 1015-graph-small-00 | q2 | Linter, Policy, Router |
| graph | no_dependents | 1015-graph-small-01 | q2 | Joiner |
| graph | no_dependents | 1015-graph-small-02 | q2 | Logger |
| graph | no_dependents | 1015-graph-small-04 | q2 | Upload |
| graph | no_dependents | 1015-graph-small-06 | q2 | Audit |
| graph | no_dependents | 1015-graph-small-07 | q2 | Ingest, Router, Search |
| graph | no_dependents | 1015-graph-small-08 | q2 | Archive, Ranker |
| graph | no_dependents | 1015-graph-small-09 | q2 | Decoder, Mailer, Tester |
| graph | path_length | 1015-graph-large-00 | q1 | 2 |
| graph | path_length | 1015-graph-large-01 | q1 | 5 |
| graph | path_length | 1015-graph-large-02 | q1 | 5 |
| graph | path_length | 1015-graph-large-03 | q1 | 5 |
| graph | path_length | 1015-graph-large-04 | q1 | 3 |
| graph | path_length | 1015-graph-large-05 | q1 | 2 |
| graph | path_length | 1015-graph-large-07 | q1 | 3 |
| graph | path_length | 1015-graph-large-08 | q1 | 2 |
| graph | path_length | 1015-graph-medium-00 | q1 | 2 |
| graph | path_length | 1015-graph-medium-01 | q1 | 2 |
| graph | path_length | 1015-graph-medium-02 | q1 | 2 |
| graph | path_length | 1015-graph-medium-07 | q1 | 2 |
| graph | path_length | 1015-graph-medium-09 | q1 | 2 |
| graph | path_length | 1015-graph-small-00 | q1 | 2 |
| graph | path_length | 1015-graph-small-04 | q1 | 2 |
| graph | path_length | 1015-graph-small-08 | q1 | 2 |
| graph | reach | 1015-graph-small-09 | q0 | yes |
| layout | below | 1015-layout-large-00 | q1 | Help |
| layout | below | 1015-layout-large-03 | q1 | Sidebar |
| layout | below | 1015-layout-large-05 | q1 | Gallery |
| layout | below | 1015-layout-large-08 | q1 | Minimap |
| layout | below | 1015-layout-medium-02 | q1 | Profile |
| layout | below | 1015-layout-medium-04 | q1 | Legend |
| layout | below | 1015-layout-medium-06 | q1 | Photos |
| layout | below | 1015-layout-medium-09 | q1 | Logo |
| layout | below | 1015-layout-small-00 | q1 | Zoom |
| layout | below | 1015-layout-small-01 | q1 | Music |
| layout | below | 1015-layout-small-05 | q1 | Clock |
| layout | below | 1015-layout-small-06 | q1 | Badge |
| layout | below | 1015-layout-small-09 | q1 | Sidebar |
| layout | right_of | 1015-layout-large-01 | q0 | Queue |
| layout | right_of | 1015-layout-large-06 | q0 | Help |

</details>

### Paired: ophanic@100 against each text arm

For the same structure and question: `o+ t−` counts calls ophanic@100 got right and the text arm got wrong; `o− t+` the reverse.

| structure | vs prose: o+ t− / o− t+ | vs json: o+ t− / o− t+ | vs list: o+ t− / o− t+ |
|---|---|---|---|
| layout | 11 / 28 (n=90) | 10 / 30 (n=90) | 9 / 27 (n=90) |
| graph | 12 / 8 (n=90) | 8 / 11 (n=90) | 13 / 9 (n=90) |
| containment | 5 / 24 (n=90) | 1 / 29 (n=90) | 0 / 27 (n=90) |

### Noise: no detectable cost

No detectable cost, ±8 points. On 135 paired calls (ophanic-noise@100 against ophanic@100 on the same structures and questions), noise minus clean is -1.5 points: 0 calls flipped to right and 2 to wrong. Each arm's own interval is about ±8 points, which can't resolve H4's 5-point threshold. The paired interval on the difference is narrower (±2.0 points) because so few calls changed, but it assumes independent calls, and noise covered half the structures and one noise recipe.

### Input tokens by structure type, against three comparators

The `all` row of the token table below is one average over an unweighted mix of types, against json pretty-printed with indent=2, the most expensive text arm. Here it is by type, against that json, against compact json (no whitespace; measured with qwen3:8b by `measure_tokens.py`, same template), and against the list. Ratios are means of paired per-call ratios.

*Whole prompt* is `prompt_eval_count` as the model reports it, which includes the question, the instruction and the chat template and so pulls every ratio toward 1. *Encoding only* subtracts a measured prompt with the question and instruction alone (the `bare` rows in tokens.jsonl).

**Whole prompt** (qwen3:8b tokenizer)

| structure | encoding | × json | × json-compact | × list |
|---|---|---|---|---|
| layout | ophanic@100 | 1.03× | 2.12× | 1.65× |
| layout | ophanic@60 | 0.78× | 1.60× | 1.24× |
| layout | prose | 0.87× | 1.81× | 1.40× |
| layout | json | 1.00× | 2.07× | 1.61× |
| layout | list | 0.62× | 1.29× | 1.00× |
| layout | json-compact | 0.49× | 1.00× | 0.78× |
| graph | ophanic@100 | 1.25× | 2.30× | 3.30× |
| graph | ophanic@60 | 1.27× | 2.33× | 3.34× |
| graph | prose | 0.30× | 0.54× | 0.78× |
| graph | json | 1.00× | 1.85× | 2.66× |
| graph | list | 0.38× | 0.70× | 1.00× |
| graph | json-compact | 0.54× | 1.00× | 1.43× |
| containment | ophanic@100 | 2.18× | 3.68× | 3.45× |
| containment | ophanic@60 | 1.93× | 3.28× | 3.06× |
| containment | prose | 0.55× | 0.94× | 0.87× |
| containment | json | 1.00× | 1.71× | 1.59× |
| containment | list | 0.63× | 1.08× | 1.00× |
| containment | json-compact | 0.59× | 1.00× | 0.93× |

**Encoding only** (qwen3:8b tokenizer)

| structure | encoding | × json | × json-compact | × list |
|---|---|---|---|---|
| layout | ophanic@100 | 1.03× | 2.38× | 1.76× |
| layout | ophanic@60 | 0.76× | 1.74× | 1.29× |
| layout | prose | 0.86× | 1.99× | 1.47× |
| layout | json | 1.00× | 2.30× | 1.71× |
| layout | list | 0.59× | 1.35× | 1.00× |
| layout | json-compact | 0.43× | 1.00× | 0.74× |
| graph | ophanic@100 | 1.28× | 2.55× | 3.94× |
| graph | ophanic@60 | 1.30× | 2.58× | 3.98× |
| graph | prose | 0.24× | 0.47× | 0.73× |
| graph | json | 1.00× | 1.99× | 3.07× |
| graph | list | 0.33× | 0.65× | 1.00× |
| graph | json-compact | 0.50× | 1.00× | 1.54× |
| containment | ophanic@100 | 2.56× | 5.31× | 4.95× |
| containment | ophanic@60 | 2.22× | 4.61× | 4.28× |
| containment | prose | 0.44× | 0.91× | 0.83× |
| containment | json | 1.00× | 2.06× | 1.89× |
| containment | list | 0.54× | 1.10× | 1.00× |
| containment | json-compact | 0.49× | 1.00× | 0.91× |

## Accuracy by encoding

| encoding | accuracy |
|---|---|
| ophanic@100 | 41% (35–47) n=270 |
| ophanic@60 | 39% (33–45) n=270 |
| ophanic-noise@100 | 39% (31–48) n=135 |
| prose | 53% (47–58) n=270 |
| json | 60% (54–65) n=270 |
| list | 56% (50–62) n=270 |

## Encoding × structure

| structure | ophanic@100 | ophanic@60 | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|
| layout | 48% (38–58) n=90 | 46% (36–56) n=90 | 47% (33–61) n=45 | 67% (56–76) n=90 | 70% (60–78) n=90 | 68% (58–77) n=90 |
| graph | 33% (24–44) n=90 | 33% (24–44) n=90 | 33% (21–48) n=45 | 29% (21–39) n=90 | 37% (27–47) n=90 | 29% (21–39) n=90 |
| containment | 41% (32–51) n=90 | 38% (28–48) n=90 | 38% (25–52) n=45 | 62% (52–72) n=90 | 72% (62–80) n=90 | 71% (61–79) n=90 |

## Encoding × structure × size

| structure | size | ophanic@100 | ophanic@60 | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|
| layout | small | 40% (25–58) n=30 | 43% (27–61) n=30 | 47% (25–70) n=15 | 67% (49–81) n=30 | 73% (56–86) n=30 | 73% (56–86) n=30 |
| layout | medium | 57% (39–73) n=30 | 50% (33–67) n=30 | 47% (25–70) n=15 | 70% (52–83) n=30 | 67% (49–81) n=30 | 67% (49–81) n=30 |
| layout | large | 47% (30–64) n=30 | 43% (27–61) n=30 | 47% (25–70) n=15 | 63% (46–78) n=30 | 70% (52–83) n=30 | 63% (46–78) n=30 |
| graph | small | 30% (17–48) n=30 | 30% (17–48) n=30 | 27% (11–52) n=15 | 30% (17–48) n=30 | 53% (36–70) n=30 | 33% (19–51) n=30 |
| graph | medium | 40% (25–58) n=30 | 37% (22–54) n=30 | 40% (20–64) n=15 | 30% (17–48) n=30 | 33% (19–51) n=30 | 23% (12–41) n=30 |
| graph | large | 30% (17–48) n=30 | 33% (19–51) n=30 | 33% (15–58) n=15 | 27% (14–44) n=30 | 23% (12–41) n=30 | 30% (17–48) n=30 |
| containment | small | 63% (46–78) n=30 | 63% (46–78) n=30 | 60% (36–80) n=15 | 90% (74–97) n=30 | 100% (89–100) n=30 | 97% (83–99) n=30 |
| containment | medium | 43% (27–61) n=30 | 30% (17–48) n=30 | 47% (25–70) n=15 | 53% (36–70) n=30 | 73% (56–86) n=30 | 67% (49–81) n=30 |
| containment | large | 17% (7–34) n=30 | 20% (10–37) n=30 | 7% (1–30) n=15 | 43% (27–61) n=30 | 43% (27–61) n=30 | 50% (33–67) n=30 |

## Encoding × structure × question kind

| structure | question (kind) | ophanic@100 | ophanic@60 | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|
| layout | below (spatial) | 30% (17–48) n=30 | 30% (17–48) n=30 | 27% (11–52) n=15 | 33% (19–51) n=30 | 43% (27–61) n=30 | 37% (22–54) n=30 |
| layout | right_of (spatial) | 67% (49–81) n=30 | 60% (42–75) n=30 | 60% (36–80) n=15 | 67% (49–81) n=30 | 70% (52–83) n=30 | 67% (49–81) n=30 |
| layout | share (proportion) | 47% (30–64) n=30 | 47% (30–64) n=30 | 53% (30–75) n=15 | 100% (89–100) n=30 | 97% (83–99) n=30 | 100% (89–100) n=30 |
| graph | no_dependents (aggregate) | 0% (0–11) n=30 | 0% (0–11) n=30 | 0% (0–20) n=15 | 0% (0–11) n=30 | 3% (1–17) n=30 | 3% (1–17) n=30 |
| graph | path_length (path) | 30% (17–48) n=30 | 27% (14–44) n=30 | 27% (11–52) n=15 | 3% (1–17) n=30 | 33% (19–51) n=30 | 10% (3–26) n=30 |
| graph | reach (path) | 70% (52–83) n=30 | 73% (56–86) n=30 | 73% (48–89) n=15 | 83% (66–93) n=30 | 73% (56–86) n=30 | 73% (56–86) n=30 |
| containment | count (count) | 23% (12–41) n=30 | 13% (5–30) n=30 | 27% (11–52) n=15 | 27% (14–44) n=30 | 57% (39–73) n=30 | 53% (36–70) n=30 |
| containment | holders (containment) | 27% (14–44) n=30 | 27% (14–44) n=30 | 27% (11–52) n=15 | 63% (46–78) n=30 | 63% (46–78) n=30 | 67% (49–81) n=30 |
| containment | inside (containment) | 73% (56–86) n=30 | 73% (56–86) n=30 | 60% (36–80) n=15 | 97% (83–99) n=30 | 97% (83–99) n=30 | 93% (79–98) n=30 |

## Noise (paired: the same structures and questions)

| structure | ophanic@100 | ophanic-noise@100 |
|---|---|---|
| layout | 51% (37–65) n=45 | 47% (33–61) n=45 |
| graph | 33% (21–48) n=45 | 33% (21–48) n=45 |
| containment | 38% (25–52) n=45 | 38% (25–52) n=45 |
| all | 41% (33–49) n=135 | 39% (31–48) n=135 |

## Input tokens per encoding

Mean `prompt_eval_count` reported by the model API per call (the encoding plus the question and instruction, under the model's chat template). The ratio is the mean of each call's count over the json call for the same structure and question.

| structure | size | ophanic@100 | ophanic@60 | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|
| layout | small | 216 (1.09×) | 165 (0.83×) | 216 (1.05×) | 180 (0.90×) | 199 (1.00×) | 133 (0.67×) |
| layout | medium | 470 (1.01×) | 354 (0.76×) | 445 (0.99×) | 396 (0.85×) | 466 (1.00×) | 285 (0.61×) |
| layout | large | 1134 (0.97×) | 853 (0.73×) | 1095 (0.94×) | 1020 (0.87×) | 1170 (1.00×) | 694 (0.59×) |
| graph | small | 381 (1.38×) | 380 (1.36×) | 394 (1.27×) | 100 (0.36×) | 282 (1.00×) | 119 (0.43×) |
| graph | medium | 868 (1.23×) | 900 (1.27×) | 890 (1.26×) | 201 (0.28×) | 718 (1.00×) | 263 (0.37×) |
| graph | large | 2078 (1.15×) | 2107 (1.16×) | 2035 (1.15×) | 450 (0.25×) | 1814 (1.00×) | 624 (0.34×) |
| containment | small | 290 (2.56×) | 245 (2.16×) | 289 (2.50×) | 71 (0.63×) | 113 (1.00×) | 76 (0.67×) |
| containment | medium | 493 (2.11×) | 441 (1.88×) | 506 (2.03×) | 128 (0.54×) | 235 (1.00×) | 144 (0.61×) |
| containment | large | 866 (1.86×) | 815 (1.75×) | 909 (1.91×) | 228 (0.49×) | 466 (1.00×) | 290 (0.62×) |
| all |  | (1.48×) | (1.32×) | (1.45×) | (0.57×) | (1.00×) | (0.55×) |

## Harness checks

- Calls with an error: 0
- Empty answers: 0
- Prompts at or over num_ctx (would be truncated): 0
- Answers over 200 characters: 89
- Latency: total 6.6 min, median 0.16 s, max 1.6 s

## All cells

| structure | size | question | ophanic@100 | ophanic@60 | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|---|
| layout | small | below | 20% (6–51) n=10 | 30% (11–60) n=10 | 20% (4–62) n=5 | 30% (11–60) n=10 | 40% (17–69) n=10 | 40% (17–69) n=10 |
| layout | small | right_of | 50% (24–76) n=10 | 50% (24–76) n=10 | 60% (23–88) n=5 | 70% (40–89) n=10 | 90% (60–98) n=10 | 80% (49–94) n=10 |
| layout | small | share | 50% (24–76) n=10 | 50% (24–76) n=10 | 60% (23–88) n=5 | 100% (72–100) n=10 | 90% (60–98) n=10 | 100% (72–100) n=10 |
| layout | medium | below | 40% (17–69) n=10 | 30% (11–60) n=10 | 20% (4–62) n=5 | 40% (17–69) n=10 | 40% (17–69) n=10 | 40% (17–69) n=10 |
| layout | medium | right_of | 90% (60–98) n=10 | 80% (49–94) n=10 | 80% (38–96) n=5 | 70% (40–89) n=10 | 60% (31–83) n=10 | 60% (31–83) n=10 |
| layout | medium | share | 40% (17–69) n=10 | 40% (17–69) n=10 | 40% (12–77) n=5 | 100% (72–100) n=10 | 100% (72–100) n=10 | 100% (72–100) n=10 |
| layout | large | below | 30% (11–60) n=10 | 30% (11–60) n=10 | 40% (12–77) n=5 | 30% (11–60) n=10 | 50% (24–76) n=10 | 30% (11–60) n=10 |
| layout | large | right_of | 60% (31–83) n=10 | 50% (24–76) n=10 | 40% (12–77) n=5 | 60% (31–83) n=10 | 60% (31–83) n=10 | 60% (31–83) n=10 |
| layout | large | share | 50% (24–76) n=10 | 50% (24–76) n=10 | 60% (23–88) n=5 | 100% (72–100) n=10 | 100% (72–100) n=10 | 100% (72–100) n=10 |
| graph | small | no_dependents | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–43) n=5 | 0% (0–28) n=10 | 10% (2–40) n=10 | 10% (2–40) n=10 |
| graph | small | path_length | 30% (11–60) n=10 | 30% (11–60) n=10 | 20% (4–62) n=5 | 10% (2–40) n=10 | 70% (40–89) n=10 | 30% (11–60) n=10 |
| graph | small | reach | 60% (31–83) n=10 | 60% (31–83) n=10 | 60% (23–88) n=5 | 80% (49–94) n=10 | 80% (49–94) n=10 | 60% (31–83) n=10 |
| graph | medium | no_dependents | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–43) n=5 | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–28) n=10 |
| graph | medium | path_length | 40% (17–69) n=10 | 30% (11–60) n=10 | 40% (12–77) n=5 | 0% (0–28) n=10 | 30% (11–60) n=10 | 0% (0–28) n=10 |
| graph | medium | reach | 80% (49–94) n=10 | 80% (49–94) n=10 | 80% (38–96) n=5 | 90% (60–98) n=10 | 70% (40–89) n=10 | 70% (40–89) n=10 |
| graph | large | no_dependents | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–43) n=5 | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–28) n=10 |
| graph | large | path_length | 20% (6–51) n=10 | 20% (6–51) n=10 | 20% (4–62) n=5 | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–28) n=10 |
| graph | large | reach | 70% (40–89) n=10 | 80% (49–94) n=10 | 80% (38–96) n=5 | 80% (49–94) n=10 | 70% (40–89) n=10 | 90% (60–98) n=10 |
| containment | small | count | 50% (24–76) n=10 | 40% (17–69) n=10 | 40% (12–77) n=5 | 70% (40–89) n=10 | 100% (72–100) n=10 | 90% (60–98) n=10 |
| containment | small | holders | 70% (40–89) n=10 | 80% (49–94) n=10 | 80% (38–96) n=5 | 100% (72–100) n=10 | 100% (72–100) n=10 | 100% (72–100) n=10 |
| containment | small | inside | 70% (40–89) n=10 | 70% (40–89) n=10 | 60% (23–88) n=5 | 100% (72–100) n=10 | 100% (72–100) n=10 | 100% (72–100) n=10 |
| containment | medium | count | 20% (6–51) n=10 | 0% (0–28) n=10 | 40% (12–77) n=5 | 10% (2–40) n=10 | 60% (31–83) n=10 | 50% (24–76) n=10 |
| containment | medium | holders | 10% (2–40) n=10 | 0% (0–28) n=10 | 0% (0–43) n=5 | 60% (31–83) n=10 | 60% (31–83) n=10 | 50% (24–76) n=10 |
| containment | medium | inside | 100% (72–100) n=10 | 90% (60–98) n=10 | 100% (57–100) n=5 | 90% (60–98) n=10 | 100% (72–100) n=10 | 100% (72–100) n=10 |
| containment | large | count | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–43) n=5 | 0% (0–28) n=10 | 10% (2–40) n=10 | 20% (6–51) n=10 |
| containment | large | holders | 0% (0–28) n=10 | 0% (0–28) n=10 | 0% (0–43) n=5 | 30% (11–60) n=10 | 30% (11–60) n=10 | 50% (24–76) n=10 |
| containment | large | inside | 50% (24–76) n=10 | 60% (31–83) n=10 | 20% (4–62) n=5 | 100% (72–100) n=10 | 90% (60–98) n=10 | 80% (49–94) n=10 |

