# PILOT 2: no hypothesis tested

**PILOT 2.** This run exists to find harness bugs. Its numbers are descriptive only and test none of DESIGN.md's hypotheses; the confirmatory run uses fresh seeds and 40 structures per cell.

- Run: `pilot2-qwen3-8b`; condition: qwen3:8b; tasks: 5016.jsonl
- Calls scored: 567; num_ctx: [6144]
- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±5 points.
- Each structure × size cell has 3 structures, each asked 3 questions. The intervals treat every call as independent: they ignore that a structure's three questions are correlated and that the arms are paired on the same structures, so they are too narrow.
- Overall and per-structure percentages mix questions at the floor (see Floors) with questions near the ceiling.

## What pilot 2 was for, and what it found

**PILOT 2 is a harness check, descriptive only.** It ran harness 2 (f869c22: the options DESIGN.md's amendments
propose, which Kohl has not yet confirmed) on qwen3:8b (Ollama 0.12.7, `think: false`, temperature 0, num_ctx 6144,
num_predict 256, stop on a blank line), seed 5016, 3 structures per type and size, 3 questions each. Arms:
ophanic@100 framed, ophanic@100+fenced, ophanic@100+unframed, prose, json, list, and ophanic-noise@100 on every
structure: 567 calls in 1.7 minutes, plus 567 token-count prompts from `measure_tokens.py`. ComfyUI stayed up.
With 3 structures per cell, every number below is a check that the machinery runs, not an estimate of anything.

**Looping: gone.** All 567 calls ended on the stop sequence or end of answer (`done_reason: stop`); none hit the
token limit and none ran over 200 characters (the longest was 180). The longest answer was 38 tokens, and it was
not clean: a `path_length` answer that began "To determine the number of edges on the shortest directed path...",
cut off by the blank-line stop after its first paragraph and scored wrong. So the stop ends loops, and it also
hides preambles. In pilot 1, 89 answers ran over 200 characters and 71 hit the 128-token limit, 67 of them
`no_dependents` lists.

**Floors: moved, not removed.** Three questions are still at or near the floor for this model, for reasons the
harness can now see:
- `share` (A1) does what it was built to do: no arm can look the answer up. qwen3:8b doesn't divide. In 24 of 27
  text-arm calls its answer's whole-number part was the stated width itself ("29" or "29.66" for "29 of 59
  characters", gold 50; 18 exactly, 25 within one), which the scorer marks wrong by design, so the text arms went from 97–100% in pilot 1 to 0/9 each. The ophanic arms still mostly
  answer 25 and sit at or below the constant-guess baseline. All arms were wrong on 5 of 9 share questions. For
  this model H1b is at the floor in every arm; it needs a model that does arithmetic (qwen3:14b with thinking, or
  Claude) to discriminate.
- `no_incoming` (A2) is now one short number in every arm, so it no longer loops, but it is right 0–22% of the
  time per arm and wrong in every arm on 5 of 9. With the ophanic arms the model tends to answer 10–14 on the larger
  graphs, which is neither the gold nor the node count.
- `path_length` was wrong in every arm on 4 of 9 (pilot 1: 16 of 30).

**Framing (A3): mechanically right, no visible effect at this size.** Every prompt in a framed arm starts with its
framing sentence, and the `+unframed` arm reproduces the pilot's prompt exactly (tests check both). Overall
ophanic@100 framed 31/81 (38%), fenced 34/81 (42%), unframed 32/81 (40%). Per-question differences between the
three go both ways (framed is lower on containment count and share, higher on layout `below`) and none is
outside what 9 calls per cell can produce. Nothing here says framing helps or hurts qwen3:8b.

**Statistics (A4, A5, A6).** The cluster bootstrap, H1a/H1b, H2, the H3 slope, the H4 equivalence check and the
H5 table all run on real data. Do not read their intervals: with 3 structures per stratum a percentile bootstrap
has about ten distinct resamples per cell and its intervals are too narrow, not merely wide (the H3 interval of
+33 to +89 points from 9 structures is the symptom). H4's interval (−3.7 to +3.7) is narrow also because only 4
of 81 noise pairs disagreed. H5's encoding-only ratios are close to pilot 1's on graphs (2.55× to 2.51× compact
json) and containment (5.31× to 5.39×). Layout moved from 2.38× to 2.16×, because the compact json now carries
widths instead of shares, and the layout ratio to the list fell from 1.76× to 1.28× because the list now carries
widths too.

**Still there from pilot 1:** the containment gap. Ophanic@100 got 10/27 on containment against 19–21/27 for the
text arms, and the paired counts lean the same way (0 / 11 against prose).

**Harness bugs found:** none in the run. One labelling fix before it: the token table in the review section
printed "graph" without A2's relabel.

## Hypotheses: the pre-registered statistics (amendments A1-A9, proposed, Kohl to confirm)

**PILOT 2: these numbers test nothing.** They are printed to check that the statistics run, with no reading against any threshold. Intervals are percentile 95% intervals from a cluster bootstrap over structures (2000 replicates, seed 0), resampling within each type × size cell and keeping each structure's arms, questions and models together.

The ophanic arm tested is `ophanic@100`.

**H1a** (layout `right_of` and `below`, medium size): ophanic@100 minus each text arm.

- vs prose: -16.7 points (95% CI -50.0 to +0.0; 3 structures, 6 pairs)
- vs list: -16.7 points (95% CI -50.0 to +0.0; 3 structures, 6 pairs)

**H1b** (layout `share`, medium size): ophanic@100 minus each text arm. `ophanic@60`, whose widths the text arms state, is not in this run: `ophanic@100` stands in, and its widths differ from the stated ones.

- vs prose: +66.7 points (95% CI +0.0 to +100.0; 3 structures, 3 pairs)
- vs list: +66.7 points (95% CI +0.0 to +100.0; 3 structures, 3 pairs)
- Constant-guess baseline: always answering 25 scores 2/3 = 67% on these questions. Accuracy: ophanic@100 67%, prose 0%, json 0%, list 0%.

**H2** (graph `reach` and `path_length`, all sizes): ophanic@100, here a partial-edge list plus picture (A2), minus json and list.

- vs json: +5.6 points (95% CI -16.7 to +22.2; 9 structures, 18 pairs)
- vs list: +27.8 points (95% CI +5.6 to +50.0; 9 structures, 18 pairs)

**H3** (layout): advantage = ophanic@100 minus the better of prose and list at each size; the statistic is large advantage minus small advantage.

- all layout questions: +55.6 points (95% CI +33.3 to +88.9; 9 structures); advantage by size: small -33.3, medium +11.1, large +22.2.
- spatial only: +83.3 points (95% CI +50.0 to +133.3; 9 structures); advantage by size: small -50.0, medium -16.7, large +33.3.

**H4** (noise, A5): noisy minus clean, against a ±5-point equivalence margin.

- ophanic-noise@100 minus ophanic@100: +0.0 points (95% CI -3.7 to +3.7; 27 structures, 81 pairs); noise on 100% of the structures.

**H5** (cost, A6): encoding-only input tokens (each model's own count minus a bare question prompt, unframed), mean of paired per-question ratios by structure type. Primary comparator compact json, then list; indented json for continuity. Threshold 1.5× compact json.

| structure | ophanic@100 × json-compact | ophanic@100 × list | ophanic@100 × json (indented) |
|---|---|---|---|
| layout | 2.16× (2.00–2.29) | 1.28× (1.19–1.35) | 0.96× (0.89–1.02) |
| graph (ophanic arm: partial-edge list plus picture) | 2.51× (2.45–2.58) | 3.85× (3.77–3.94) | 1.25× (1.23–1.29) |
| containment | 5.39× (4.99–5.86) | 5.06× (4.27–6.02) | 2.62× (2.47–2.80) |

**H6** (construction): **not run.** It is not built, so it is not part of any run until it is built and reviewed (A9).

## Checks from the pilot review

Computed by score.py from calls.jsonl (and tokens.jsonl for the cost table), at Momus's request. Like everything else here, these are descriptive.

### Layout: spatial questions versus the proportion question

Spatial is `right_of` plus `below`; proportion is `share`. Every arm has to compute the share (A1): the prose, json and list encodings state character widths ("24 of 59 characters"), and the ophanic encodings draw them.

| encoding | layout spatial | layout proportion |
|---|---|---|
| ophanic@100 | 8/18 = 44% (25–66) | 2/9 = 22% (6–55) |
| ophanic@100+fenced | 10/18 = 56% (34–75) | 2/9 = 22% (6–55) |
| ophanic@100+unframed | 6/18 = 33% (16–56) | 4/9 = 44% (19–73) |
| ophanic-noise@100 | 8/18 = 44% (25–66) | 2/9 = 22% (6–55) |
| prose | 8/18 = 44% (25–66) | 0/9 = 0% (0–30) |
| json | 10/18 = 56% (34–75) | 0/9 = 0% (0–30) |
| list | 10/18 = 56% (34–75) | 0/9 = 0% (0–30) |

### Proportion answers: the "25" default and a constant-guess baseline

| encoding | share calls | answered exactly 25 | mean absolute error (points) | accuracy |
|---|---|---|---|---|
| ophanic@100 | 9 | 7 | 15.6 | 2/9 = 22% (6–55) |
| ophanic@100+fenced | 9 | 5 | 12.8 | 2/9 = 22% (6–55) |
| ophanic@100+unframed | 9 | 5 | 11.3 | 4/9 = 44% (19–73) |
| ophanic-noise@100 | 9 | 5 | 12.2 | 2/9 = 22% (6–55) |
| prose | 9 | 0 | 16.2 | 0/9 = 0% (0–30) |
| json | 9 | 0 | 16.6 | 0/9 = 0% (0–30) |
| list | 9 | 0 | 17.0 | 0/9 = 0% (0–30) |

Gold shares over the 9 share questions: 20 ×3, 30 ×1, 35 ×1, 45 ×1, 50 ×3.
Always answering 25 would score 4/9 = 44% under the ±5 rule; no other constant does better. An ophanic share accuracy at or below that is indistinguishable from a guess, and is no evidence that the model reads widths.

### Floors: questions every arm got wrong

A question counts here when all of ophanic@100, ophanic@100+fenced, ophanic@100+unframed, prose, json, list answered it wrong. A question with no scored answer in some arm (an error, or a call that gave no answer) is left out of the count, so the denominators can be smaller than the structures asked. A11's floor rule: more than half.

| structure | question | wrong in every arm |
|---|---|---|
| layout | below | 2 of 9 |
| layout | right_of | 1 of 9 |
| layout | share | 5 of 9 |
| graph (ophanic arm: partial-edge list plus picture) | no_incoming | 5 of 9 |
| graph (ophanic arm: partial-edge list plus picture) | path_length | 4 of 9 |
| graph (ophanic arm: partial-edge list plus picture) | reach | 0 of 9 |
| containment | count | 2 of 9 |
| containment | holders | 1 of 9 |
| containment | inside | 0 of 9 |

On graphs the arms look level because the graph questions are near the floor, not because the encodings are at parity: `no_incoming` was wrong in every arm on 5 of 9; `path_length` was wrong in every arm on 4 of 9; `reach` was wrong in every arm on 0 of 9.

<details><summary>The cases (structure, question, gold)</summary>

| structure | question | task | id | gold |
|---|---|---|---|---|
| containment | count | 5016-containment-large-00 | q2 | 11 |
| containment | count | 5016-containment-large-02 | q2 | 7 |
| containment | holders | 5016-containment-large-00 | q1 | Maple, Orion |
| graph | no_incoming | 5016-graph-large-02 | q2 | 3 |
| graph | no_incoming | 5016-graph-medium-00 | q2 | 7 |
| graph | no_incoming | 5016-graph-medium-01 | q2 | 5 |
| graph | no_incoming | 5016-graph-medium-02 | q2 | 3 |
| graph | no_incoming | 5016-graph-small-02 | q2 | 3 |
| graph | path_length | 5016-graph-large-00 | q1 | 2 |
| graph | path_length | 5016-graph-large-01 | q1 | 2 |
| graph | path_length | 5016-graph-small-00 | q1 | 3 |
| graph | path_length | 5016-graph-small-01 | q1 | 2 |
| layout | below | 5016-layout-large-02 | q1 | Search |
| layout | below | 5016-layout-medium-02 | q1 | Table |
| layout | right_of | 5016-layout-medium-01 | q0 | Layers |
| layout | share | 5016-layout-large-01 | q2 | 35 |
| layout | share | 5016-layout-medium-02 | q2 | 45 |
| layout | share | 5016-layout-small-00 | q2 | 50 |
| layout | share | 5016-layout-small-01 | q2 | 50 |
| layout | share | 5016-layout-small-02 | q2 | 50 |

</details>

### Paired: ophanic@100 against each text arm

For the same structure and question: `o+ t−` counts calls ophanic@100 got right and the text arm got wrong; `o− t+` the reverse.

| structure | vs prose: o+ t− / o− t+ | vs json: o+ t− / o− t+ | vs list: o+ t− / o− t+ |
|---|---|---|---|
| layout | 6 / 4 (n=27) | 6 / 6 (n=27) | 6 / 6 (n=27) |
| graph (ophanic arm: partial-edge list plus picture) | 8 / 3 (n=27) | 5 / 3 (n=27) | 7 / 3 (n=27) |
| containment | 0 / 11 (n=27) | 1 / 10 (n=27) | 2 / 12 (n=27) |

### Noise: the paired difference

On 81 paired calls (ophanic-noise@100 against ophanic@100 on the same structures and questions), noise minus clean is +0.0 points: 2 calls flipped to right and 2 to wrong. Each arm's own interval is about ±11 points. The naive paired interval on the difference is ±4.8 points, but it assumes independent calls; the cluster-bootstrap interval under Hypotheses (H4) is the one to read. Noise covered 100% of the structures, with one noise recipe.

### Input tokens by structure type, against three comparators

The `all` row of the token table below is one average over an unweighted mix of types, against json pretty-printed with indent=2, the most expensive text arm. Here it is by type, against that json, against compact json (no whitespace; measured by `measure_tokens.py`, same template), and against the list. Ratios are means of paired per-call ratios. Where `measure_tokens.py` measured an arm's unframed prompt, that count is used; otherwise the call's own count.

*Whole prompt* is `prompt_eval_count` as the model reports it, which includes the question, the instruction and the chat template and so pulls every ratio toward 1. *Encoding only* subtracts a measured prompt with the question and instruction alone (the `bare` rows in tokens.jsonl).

**Whole prompt** (qwen3:8b tokenizer)

| structure | encoding | × json | × json-compact | × list |
|---|---|---|---|---|
| layout | ophanic@100 | 0.96× | 1.95× | 1.25× |
| layout | prose | 0.95× | 1.94× | 1.24× |
| layout | json | 1.00× | 2.03× | 1.30× |
| layout | list | 0.77× | 1.57× | 1.00× |
| layout | json-compact | 0.49× | 1.00× | 0.64× |
| graph (ophanic arm: partial-edge list plus picture) | ophanic@100 | 1.23× | 2.29× | 3.28× |
| graph (ophanic arm: partial-edge list plus picture) | prose | 0.29× | 0.54× | 0.77× |
| graph (ophanic arm: partial-edge list plus picture) | json | 1.00× | 1.87× | 2.68× |
| graph (ophanic arm: partial-edge list plus picture) | list | 0.38× | 0.70× | 1.00× |
| graph (ophanic arm: partial-edge list plus picture) | json-compact | 0.54× | 1.00× | 1.43× |
| containment | ophanic@100 | 2.22× | 3.73× | 3.45× |
| containment | prose | 0.56× | 0.94× | 0.87× |
| containment | json | 1.00× | 1.69× | 1.55× |
| containment | list | 0.65× | 1.09× | 1.00× |
| containment | json-compact | 0.59× | 1.00× | 0.92× |

**Encoding only** (qwen3:8b tokenizer)

| structure | encoding | × json | × json-compact | × list |
|---|---|---|---|---|
| layout | ophanic@100 | 0.96× | 2.16× | 1.28× |
| layout | prose | 0.95× | 2.13× | 1.26× |
| layout | json | 1.00× | 2.24× | 1.33× |
| layout | list | 0.75× | 1.68× | 1.00× |
| layout | json-compact | 0.45× | 1.00× | 0.59× |
| graph (ophanic arm: partial-edge list plus picture) | ophanic@100 | 1.25× | 2.51× | 3.85× |
| graph (ophanic arm: partial-edge list plus picture) | prose | 0.24× | 0.47× | 0.72× |
| graph (ophanic arm: partial-edge list plus picture) | json | 1.00× | 2.00× | 3.07× |
| graph (ophanic arm: partial-edge list plus picture) | list | 0.33× | 0.65× | 1.00× |
| graph (ophanic arm: partial-edge list plus picture) | json-compact | 0.50× | 1.00× | 1.53× |
| containment | ophanic@100 | 2.62× | 5.39× | 5.06× |
| containment | prose | 0.45× | 0.92× | 0.83× |
| containment | json | 1.00× | 2.05× | 1.87× |
| containment | list | 0.55× | 1.12× | 1.00× |
| containment | json-compact | 0.49× | 1.00× | 0.91× |

## Accuracy by encoding

| encoding | accuracy |
|---|---|
| ophanic@100 | 38% (28–49) n=81 |
| ophanic@100+fenced | 42% (32–53) n=81 |
| ophanic@100+unframed | 40% (30–50) n=81 |
| ophanic-noise@100 | 38% (28–49) n=81 |
| prose | 43% (33–54) n=81 |
| json | 47% (36–58) n=81 |
| list | 46% (35–56) n=81 |

## Encoding × structure

| structure | ophanic@100 | ophanic@100+fenced | ophanic@100+unframed | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|
| layout | 37% (22–56) n=27 | 44% (28–63) n=27 | 37% (22–56) n=27 | 37% (22–56) n=27 | 30% (16–48) n=27 | 37% (22–56) n=27 | 37% (22–56) n=27 |
| graph (ophanic arm: partial-edge list plus picture) | 41% (25–59) n=27 | 33% (19–52) n=27 | 37% (22–56) n=27 | 41% (25–59) n=27 | 22% (11–41) n=27 | 33% (19–52) n=27 | 26% (13–45) n=27 |
| containment | 37% (22–56) n=27 | 48% (31–66) n=27 | 44% (28–63) n=27 | 37% (22–56) n=27 | 78% (59–89) n=27 | 70% (52–84) n=27 | 74% (55–87) n=27 |

## Encoding × structure × size

| structure | size | ophanic@100 | ophanic@100+fenced | ophanic@100+unframed | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|---|
| layout | small | 22% (6–55) n=9 | 44% (19–73) n=9 | 22% (6–55) n=9 | 22% (6–55) n=9 | 44% (19–73) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 |
| layout | medium | 44% (19–73) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 44% (19–73) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 |
| layout | large | 44% (19–73) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 44% (19–73) n=9 | 11% (2–44) n=9 | 22% (6–55) n=9 | 22% (6–55) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | small | 56% (27–81) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 56% (27–81) n=9 | 0% (0–30) n=9 | 22% (6–55) n=9 | 33% (12–65) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | medium | 33% (12–65) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | large | 33% (12–65) n=9 | 33% (12–65) n=9 | 44% (19–73) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 44% (19–73) n=9 | 11% (2–44) n=9 |
| containment | small | 56% (27–81) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 |
| containment | medium | 22% (6–55) n=9 | 33% (12–65) n=9 | 56% (27–81) n=9 | 22% (6–55) n=9 | 78% (45–94) n=9 | 78% (45–94) n=9 | 67% (35–88) n=9 |
| containment | large | 33% (12–65) n=9 | 56% (27–81) n=9 | 22% (6–55) n=9 | 33% (12–65) n=9 | 56% (27–81) n=9 | 33% (12–65) n=9 | 56% (27–81) n=9 |

## Encoding × structure × question kind

| structure | question (kind) | ophanic@100 | ophanic@100+fenced | ophanic@100+unframed | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|---|
| layout | below (spatial) | 44% (19–73) n=9 | 56% (27–81) n=9 | 22% (6–55) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 44% (19–73) n=9 | 44% (19–73) n=9 |
| layout | right_of (spatial) | 44% (19–73) n=9 | 56% (27–81) n=9 | 44% (19–73) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 67% (35–88) n=9 | 67% (35–88) n=9 |
| layout | share (proportion) | 22% (6–55) n=9 | 22% (6–55) n=9 | 44% (19–73) n=9 | 22% (6–55) n=9 | 0% (0–30) n=9 | 0% (0–30) n=9 | 0% (0–30) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | no_incoming (aggregate) | 11% (2–44) n=9 | 0% (0–30) n=9 | 22% (6–55) n=9 | 11% (2–44) n=9 | 11% (2–44) n=9 | 0% (0–30) n=9 | 22% (6–55) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | path_length (path) | 33% (12–65) n=9 | 22% (6–55) n=9 | 33% (12–65) n=9 | 33% (12–65) n=9 | 0% (0–30) n=9 | 33% (12–65) n=9 | 0% (0–30) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | reach (path) | 78% (45–94) n=9 | 78% (45–94) n=9 | 56% (27–81) n=9 | 78% (45–94) n=9 | 56% (27–81) n=9 | 67% (35–88) n=9 | 56% (27–81) n=9 |
| containment | count (count) | 0% (0–30) n=9 | 11% (2–44) n=9 | 33% (12–65) n=9 | 0% (0–30) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 67% (35–88) n=9 |
| containment | holders (containment) | 33% (12–65) n=9 | 44% (19–73) n=9 | 44% (19–73) n=9 | 33% (12–65) n=9 | 78% (45–94) n=9 | 78% (45–94) n=9 | 78% (45–94) n=9 |
| containment | inside (containment) | 78% (45–94) n=9 | 89% (56–98) n=9 | 56% (27–81) n=9 | 78% (45–94) n=9 | 100% (70–100) n=9 | 78% (45–94) n=9 | 78% (45–94) n=9 |

## Noise (paired: the same structures and questions)

| structure | ophanic@100 | ophanic-noise@100 |
|---|---|---|
| layout | 37% (22–56) n=27 | 37% (22–56) n=27 |
| graph (ophanic arm: partial-edge list plus picture) | 41% (25–59) n=27 | 41% (25–59) n=27 |
| containment | 37% (22–56) n=27 | 37% (22–56) n=27 |
| all | 38% (28–49) n=81 | 38% (28–49) n=81 |

## Input tokens per encoding

Mean `prompt_eval_count` reported by the model API per call (the prompt as sent: the framing sentence when framing is on, the encoding, the question and instruction, under the model's chat template). The ratio is the mean of each call's count over the json call for the same structure and question.

| structure | size | ophanic@100 | ophanic@100+fenced | ophanic@100+unframed | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|---|
| layout | small | 288 (1.06×) | 290 (1.07×) | 219 (0.80×) | 284 (1.05×) | 247 (0.89×) | 275 (1.00×) | 214 (0.78×) |
| layout | medium | 492 (0.92×) | 494 (0.93×) | 423 (0.79×) | 491 (0.92×) | 467 (0.87×) | 535 (1.00×) | 399 (0.74×) |
| layout | large | 1295 (0.96×) | 1298 (0.97×) | 1226 (0.91×) | 1294 (0.96×) | 1241 (0.93×) | 1334 (1.00×) | 990 (0.74×) |
| graph (ophanic arm: partial-edge list plus picture) | small | 474 (1.45×) | 479 (1.47×) | 393 (1.20×) | 473 (1.45×) | 137 (0.42×) | 327 (1.00×) | 157 (0.48×) |
| graph (ophanic arm: partial-edge list plus picture) | medium | 897 (1.28×) | 902 (1.29×) | 816 (1.16×) | 896 (1.28×) | 217 (0.31×) | 699 (1.00×) | 274 (0.39×) |
| graph (ophanic arm: partial-edge list plus picture) | large | 2388 (1.18×) | 2393 (1.18×) | 2307 (1.14×) | 2386 (1.18×) | 524 (0.26×) | 2044 (1.00×) | 720 (0.35×) |
| containment | small | 342 (2.50×) | 344 (2.51×) | 292 (2.13×) | 342 (2.49×) | 94 (0.68×) | 138 (1.00×) | 107 (0.77×) |
| containment | medium | 507 (2.19×) | 509 (2.20×) | 457 (1.97×) | 505 (2.18×) | 131 (0.56×) | 232 (1.00×) | 154 (0.66×) |
| containment | large | 978 (1.92×) | 980 (1.92×) | 928 (1.82×) | 980 (1.92×) | 263 (0.52×) | 509 (1.00×) | 348 (0.68×) |
| all |  | (1.50×) | (1.50×) | (1.33×) | (1.49×) | (0.60×) | (1.00×) | (0.62×) |

## Harness checks

- Calls with an error (left out of scoring; a call with no answer is one): 0
- Empty answers: 0
- Prompts at or over num_ctx (would be truncated): 0
- Answers over 200 characters: 0
- Answers cut off by the token limit: 0
- Settings (harness, framing, stop, max tokens, think): 2, pilot2, '\n\n', 256, False
- Latency: total 1.7 min, median 0.15 s, max 1.8 s

## All cells

| structure | size | question | ophanic@100 | ophanic@100+fenced | ophanic@100+unframed | ophanic-noise@100 | prose | json | list |
|---|---|---|---|---|---|---|---|---|---|
| layout | small | below | 33% (6–79) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 |
| layout | small | right_of | 33% (6–79) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 |
| layout | small | share | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 |
| layout | medium | below | 33% (6–79) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 |
| layout | medium | right_of | 33% (6–79) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 |
| layout | medium | share | 67% (21–94) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 |
| layout | large | below | 67% (21–94) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 |
| layout | large | right_of | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 |
| layout | large | share | 0% (0–56) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | small | no_incoming | 33% (6–79) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 67% (21–94) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | small | path_length | 33% (6–79) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | small | reach | 100% (44–100) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | medium | no_incoming | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | medium | path_length | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | medium | reach | 33% (6–79) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | large | no_incoming | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | large | path_length | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | large | reach | 100% (44–100) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 33% (6–79) n=3 |
| containment | small | count | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| containment | small | holders | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| containment | small | inside | 100% (44–100) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| containment | medium | count | 0% (0–56) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 |
| containment | medium | holders | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 |
| containment | medium | inside | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 |
| containment | large | count | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 |
| containment | large | holders | 33% (6–79) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 |
| containment | large | inside | 67% (21–94) n=3 | 100% (44–100) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 |

