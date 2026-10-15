# PILOT 3: no hypothesis tested

This run holds 2 model and thinking conditions: qwen3:14b, qwen3:14b (thinking). Each is reported and tested on its own below; no number pools them.

## What pilot 3 was for, and what it found

**PILOT 3 is a floor pilot, descriptive only** (Momus's pilot-2 review, item 2; A11). It asks one thing: which
questions are wrong in every arm for qwen3:14b, with and without thinking. Harness 3 (3e57dfd: matched framing,
the `list-lookup` control), seed 7117 (outside the reserved 2000–2999), Ollama 0.12.7, temperature 0, num_ctx 8192.
ComfyUI was stopped for the run and restarted after it.

- **qwen3:14b, no thinking:** 3 structures per type and size (27 structures, 81 questions), arms ophanic@100,
  ophanic@60, prose, json, list, plus `list-lookup` on layouts; num_predict 256, blank-line stop. 432 calls,
  1.6 minutes, no errors, nothing cut off.
- **qwen3:14b, thinking (cut down):** `--think --max-tokens 4096 --stop '' --retries 0`. A timing test put a
  thinking call at about 20 seconds and an ophanic share call at the 4096-token limit (77 s per attempt), so the
  full design would have run for hours. To fit about 40 minutes it ran **1 structure per type and size (index 0
  of the same seed: 9 structures, 27 questions) and four arms (ophanic@100, prose, json, list) plus `list-lookup`**:
  117 calls, 31 minutes. Its floor rates are over 2–3 items each and say only whether a floor is obvious.

**All-arms-wrong rates** (the Floors tables below; A11's rule is "more than half"):

| question | 14b, no thinking (of 9) | 14b, thinking (of the items scored in every arm) |
|---|---|---|
| layout below | 1 | 0 of 3 |
| layout right_of | 0 | 0 of 2 |
| layout share | 2 | none scorable (ophanic@100 gave no answer on all 3) |
| graph no_incoming | **6** | 0 of 2 |
| graph path_length | **5** | 0 of 3 |
| graph reach | 1 | 0 of 3 |
| containment count | 3 | 0 of 2 |
| containment holders | 1 | 0 of 2 |
| containment inside | 0 | 0 of 3 |

**Without thinking, 14b divides but doesn't count.** Unlike 8b, it computes the share from stated widths: the text
arms got share 7, 6 and 7 of 9 right against the lookup ceiling's 9 of 9, and ophanic@100 4 of 9, ophanic@60 3 of 9.
So H1b is measurable for this condition. But `no_incoming` (6 of 9) and `path_length` (5 of 9) are over the floor
rule, so under A11 they would be reported descriptively and `path_length` left out of H2 for this condition.

**With thinking, 14b is near the ceiling, and the misses are informative.** Every arm scored 86–100% on what it
answered (ophanic@100 19 of 20, prose 25 of 26, json 25 of 26, list 26 of 27, list-lookup 8 of 8), and no question
was wrong in every arm. A ceiling is as uninformative as a floor: at 95% everywhere, H1 and H2 have no room. The
other finding is the 10 calls that ran out of tokens without an answer: 7 of them were ophanic@100, including
**all three ophanic share questions** (the model counted characters until 4096 tokens ran out), against one each
for prose, json and list-lookup. Those calls are left out of scoring, as designed, but they aren't missing at
random: they fall on the hardest ophanic items. Left out, they make the ophanic arm look better than it is. A
confirmatory thinking run needs either a token budget large enough that no-answer calls are rare, or a pre-registered
rule that counts a no-answer as wrong for the arm (with the rate reported per arm). This is a design question for
Kohl, not something the harness should decide.

**Harness.** No bugs found. The matched framing, the lookup arm, the no-answer path (retries off, errors recorded
and not scored) and the per-condition report all behaved as built. One fix after the run: the Floors section no
longer prints "the graph questions are near the floor" when they aren't, and it now says that errored items are left
out of its counts.

# Condition: qwen3:14b


**PILOT 3.** This run exists to find harness bugs. Its numbers are descriptive only and test none of DESIGN.md's hypotheses; the confirmatory run uses fresh seeds and 40 structures per cell.

- Run: `pilot3-qwen3-14b`; condition: qwen3:14b; tasks: 7117.jsonl
- Calls scored: 432; num_ctx: [8192]
- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±5 points.
- Each structure × size cell has 3 structures, each asked 3 questions. The intervals treat every call as independent: they ignore that a structure's three questions are correlated and that the arms are paired on the same structures, so they are too narrow.
- Overall and per-structure percentages mix questions at the floor (see Floors) with questions near the ceiling.

### Hypotheses: the pre-registered statistics (amendments A1-A9, proposed, Kohl to confirm)

**PILOT 3: these numbers test nothing.** They are printed to check that the statistics run, with no reading against any threshold. Intervals are percentile 95% intervals from a cluster bootstrap over structures (2000 replicates, seed 0), resampling within each type × size cell and keeping each structure's arms, questions and models together.

The ophanic arm tested is `ophanic@100`.

**H1a** (layout `right_of` and `below`, medium size): ophanic@100 minus each text arm.

- vs prose: +16.7 points (95% CI +0.0 to +50.0; 3 structures, 6 pairs)
- vs list: +16.7 points (95% CI +0.0 to +50.0; 3 structures, 6 pairs)

**H1b** (layout `share`, medium size): ophanic@60 minus each text arm. The text arms state the widths ophanic@60 draws, so H1b pairs them with `ophanic@60`.

- vs prose: -33.3 points (95% CI -100.0 to +0.0; 3 structures, 3 pairs)
- vs list: -33.3 points (95% CI -100.0 to +0.0; 3 structures, 3 pairs)
- Constant-guess baseline: always answering 50 scores 2/3 = 67% on these questions. Accuracy: ophanic@60 33%, prose 67%, json 67%, list 67%, list-lookup 100%.
- `list-lookup` is the lookup ceiling (A12): the same question with the percentage stated. It is a control, never a comparator in a test.

**H2** (graph `reach` and `path_length`, all sizes): ophanic@100, here a partial-edge list plus picture (A2), minus json and list.

- vs json: -16.7 points (95% CI -38.9 to +0.0; 9 structures, 18 pairs)
- vs list: -11.1 points (95% CI -22.2 to +0.0; 9 structures, 18 pairs)

**H3** (layout): advantage = ophanic@100 minus the better of prose and list at each size; the statistic is large advantage minus small advantage.

- all layout questions: -55.6 points (95% CI -66.7 to -33.3; 9 structures); advantage by size: small +0.0, medium +0.0, large -55.6.
- spatial only: -50.0 points (95% CI -50.0 to -50.0; 9 structures); advantage by size: small +0.0, medium +16.7, large -50.0.

**H4** (noise, A5): noisy minus clean, against a ±5-point equivalence margin.

- No noise arm paired with ophanic@100 in this run.

**H5** (cost, A6): encoding-only input tokens (each model's own count minus a bare question prompt, unframed), mean of paired per-question ratios by structure type. Primary comparator compact json, then list; indented json for continuity. Threshold 1.5× compact json.

- No `measure_tokens.py` counts for `ophanic@100` in tokens.jsonl: run it to fill this in.

**H6** (construction): **not run.** It is not built, so it is not part of any run until it is built and reviewed (A9).

### Checks from the pilot review

Computed by score.py from calls.jsonl (and tokens.jsonl for the cost table), at Momus's request. Like everything else here, these are descriptive.

#### Layout: spatial questions versus the proportion question

Spatial is `right_of` plus `below`; proportion is `share`. Every arm has to compute the share (A1): the prose, json and list encodings state character widths ("24 of 59 characters"), and the ophanic encodings draw them.

| encoding | layout spatial | layout proportion |
|---|---|---|
| ophanic@100 | 13/18 = 72% (49–88) | 4/9 = 44% (19–73) |
| ophanic@60 | 15/18 = 83% (61–94) | 3/9 = 33% (12–65) |
| prose | 13/18 = 72% (49–88) | 7/9 = 78% (45–94) |
| json | 14/18 = 78% (55–91) | 6/9 = 67% (35–88) |
| list | 15/18 = 83% (61–94) | 7/9 = 78% (45–94) |
| list-lookup | 13/18 = 72% (49–88) | 9/9 = 100% (70–100) |

#### Proportion answers: the "25" default and a constant-guess baseline

| encoding | share calls | answered exactly 25 | mean absolute error (points) | accuracy |
|---|---|---|---|---|
| ophanic@100 | 9 | 0 | 16.1 | 4/9 = 44% (19–73) |
| ophanic@60 | 9 | 0 | 21.0 | 3/9 = 33% (12–65) |
| prose | 9 | 0 | 7.0 | 7/9 = 78% (45–94) |
| json | 9 | 0 | 7.7 | 6/9 = 67% (35–88) |
| list | 9 | 0 | 6.1 | 7/9 = 78% (45–94) |
| list-lookup | 9 | 0 | 0.0 | 9/9 = 100% (70–100) |

Gold shares over the 9 share questions: 30 ×2, 35 ×4, 55 ×3.
Always answering 25 would score 2/9 = 22% under the ±5 rule; the best constant (30) would score 6/9 = 67%. An ophanic share accuracy at or below that is indistinguishable from a guess, and is no evidence that the model reads widths.

#### Floors: questions every arm got wrong

A question counts here when all of ophanic@100, ophanic@60, prose, json, list answered it wrong. A question with no scored answer in some arm (an error, or a call that gave no answer) is left out of the count, so the denominators can be smaller than the structures asked. A11's floor rule: more than half.

| structure | question | wrong in every arm |
|---|---|---|
| layout | below | 1 of 9 |
| layout | right_of | 0 of 9 |
| layout | share | 2 of 9 |
| graph (ophanic arm: partial-edge list plus picture) | no_incoming | 6 of 9 |
| graph (ophanic arm: partial-edge list plus picture) | path_length | 5 of 9 |
| graph (ophanic arm: partial-edge list plus picture) | reach | 1 of 9 |
| containment | count | 3 of 9 |
| containment | holders | 1 of 9 |
| containment | inside | 0 of 9 |

On graphs the arms look level because the graph questions are near the floor, not because the encodings are at parity: `no_incoming` was wrong in every arm on 6 of 9; `path_length` was wrong in every arm on 5 of 9; `reach` was wrong in every arm on 1 of 9.

<details><summary>The cases (structure, question, gold)</summary>

| structure | question | task | id | gold |
|---|---|---|---|---|
| containment | count | 7117-containment-large-00 | q2 | 10 |
| containment | count | 7117-containment-medium-00 | q2 | 8 |
| containment | count | 7117-containment-medium-02 | q2 | 12 |
| containment | holders | 7117-containment-medium-02 | q1 | Nova |
| graph | no_incoming | 7117-graph-large-00 | q2 | 8 |
| graph | no_incoming | 7117-graph-large-01 | q2 | 6 |
| graph | no_incoming | 7117-graph-large-02 | q2 | 5 |
| graph | no_incoming | 7117-graph-medium-01 | q2 | 5 |
| graph | no_incoming | 7117-graph-medium-02 | q2 | 4 |
| graph | no_incoming | 7117-graph-small-02 | q2 | 1 |
| graph | path_length | 7117-graph-large-00 | q1 | 2 |
| graph | path_length | 7117-graph-large-01 | q1 | 4 |
| graph | path_length | 7117-graph-medium-00 | q1 | 2 |
| graph | path_length | 7117-graph-medium-01 | q1 | 2 |
| graph | path_length | 7117-graph-medium-02 | q1 | 2 |
| graph | reach | 7117-graph-medium-00 | q0 | no |
| layout | below | 7117-layout-medium-02 | q1 | Share |
| layout | share | 7117-layout-large-02 | q2 | 55 |
| layout | share | 7117-layout-medium-01 | q2 | 55 |

</details>

#### Paired: ophanic@100 against each text arm

For the same structure and question: `o+ t−` counts calls ophanic@100 got right and the text arm got wrong; `o− t+` the reverse.

| structure | vs prose: o+ t− / o− t+ | vs json: o+ t− / o− t+ | vs list: o+ t− / o− t+ |
|---|---|---|---|
| layout | 2 / 5 (n=27) | 2 / 5 (n=27) | 1 / 6 (n=27) |
| graph (ophanic arm: partial-edge list plus picture) | 4 / 4 (n=27) | 1 / 5 (n=27) | 1 / 2 (n=27) |
| containment | 0 / 4 (n=27) | 0 / 8 (n=27) | 0 / 6 (n=27) |

### Accuracy by encoding

| encoding | accuracy |
|---|---|
| ophanic@100 | 49% (39–60) n=81 |
| ophanic@60 | 49% (39–60) n=81 |
| prose | 58% (47–68) n=81 |
| json | 68% (57–77) n=81 |
| list | 64% (53–74) n=81 |
| list-lookup | 81% (63–92) n=27 |

### Encoding × structure

| structure | ophanic@100 | ophanic@60 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|
| layout | 63% (44–78) n=27 | 67% (48–81) n=27 | 74% (55–87) n=27 | 74% (55–87) n=27 | 81% (63–92) n=27 | 81% (63–92) n=27 |
| graph (ophanic arm: partial-edge list plus picture) | 30% (16–48) n=27 | 26% (13–45) n=27 | 30% (16–48) n=27 | 44% (28–63) n=27 | 33% (19–52) n=27 | — |
| containment | 56% (37–72) n=27 | 56% (37–72) n=27 | 70% (52–84) n=27 | 85% (68–94) n=27 | 78% (59–89) n=27 | — |

### Encoding × structure × size

| structure | size | ophanic@100 | ophanic@60 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|---|
| layout | small | 100% (70–100) n=9 | 89% (56–98) n=9 | 100% (70–100) n=9 | 89% (56–98) n=9 | 100% (70–100) n=9 | 78% (45–94) n=9 |
| layout | medium | 56% (27–81) n=9 | 67% (35–88) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 67% (35–88) n=9 |
| layout | large | 33% (12–65) n=9 | 44% (19–73) n=9 | 67% (35–88) n=9 | 78% (45–94) n=9 | 89% (56–98) n=9 | 100% (70–100) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | small | 33% (12–65) n=9 | 33% (12–65) n=9 | 44% (19–73) n=9 | 67% (35–88) n=9 | 44% (19–73) n=9 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | 33% (12–65) n=9 | 22% (6–55) n=9 | 11% (2–44) n=9 | 22% (6–55) n=9 | 22% (6–55) n=9 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | 22% (6–55) n=9 | 22% (6–55) n=9 | 33% (12–65) n=9 | 44% (19–73) n=9 | 33% (12–65) n=9 | — |
| containment | small | 100% (70–100) n=9 | 67% (35–88) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | — |
| containment | medium | 33% (12–65) n=9 | 44% (19–73) n=9 | 44% (19–73) n=9 | 67% (35–88) n=9 | 56% (27–81) n=9 | — |
| containment | large | 33% (12–65) n=9 | 56% (27–81) n=9 | 67% (35–88) n=9 | 89% (56–98) n=9 | 78% (45–94) n=9 | — |

### Encoding × structure × question kind

| structure | question (kind) | ophanic@100 | ophanic@60 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|---|
| layout | below (spatial) | 67% (35–88) n=9 | 78% (45–94) n=9 | 56% (27–81) n=9 | 67% (35–88) n=9 | 67% (35–88) n=9 | 44% (19–73) n=9 |
| layout | right_of (spatial) | 78% (45–94) n=9 | 89% (56–98) n=9 | 89% (56–98) n=9 | 89% (56–98) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 |
| layout | share (proportion) | 44% (19–73) n=9 | 33% (12–65) n=9 | 78% (45–94) n=9 | 67% (35–88) n=9 | 78% (45–94) n=9 | 100% (70–100) n=9 |
| graph (ophanic arm: partial-edge list plus picture) | no_incoming (aggregate) | 11% (2–44) n=9 | 0% (0–30) n=9 | 11% (2–44) n=9 | 22% (6–55) n=9 | 0% (0–30) n=9 | — |
| graph (ophanic arm: partial-edge list plus picture) | path_length (path) | 11% (2–44) n=9 | 22% (6–55) n=9 | 22% (6–55) n=9 | 22% (6–55) n=9 | 22% (6–55) n=9 | — |
| graph (ophanic arm: partial-edge list plus picture) | reach (path) | 67% (35–88) n=9 | 56% (27–81) n=9 | 56% (27–81) n=9 | 89% (56–98) n=9 | 78% (45–94) n=9 | — |
| containment | count (count) | 33% (12–65) n=9 | 0% (0–30) n=9 | 44% (19–73) n=9 | 67% (35–88) n=9 | 56% (27–81) n=9 | — |
| containment | holders (containment) | 44% (19–73) n=9 | 67% (35–88) n=9 | 67% (35–88) n=9 | 89% (56–98) n=9 | 78% (45–94) n=9 | — |
| containment | inside (containment) | 89% (56–98) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | — |

### Input tokens per encoding

Mean `prompt_eval_count` reported by the model API per call (the prompt as sent: the framing sentence when framing is on, the encoding, the question and instruction, under the model's chat template). The ratio is the mean of each call's count over the json call for the same structure and question.

| structure | size | ophanic@100 | ophanic@60 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|---|
| layout | small | 275 (1.12×) | 234 (0.96×) | 226 (0.91×) | 248 (1.00×) | 208 (0.84×) | 170 (0.69×) |
| layout | medium | 575 (0.94×) | 448 (0.73×) | 588 (0.94×) | 621 (1.00×) | 493 (0.79×) | 371 (0.60×) |
| layout | large | 1185 (0.93×) | 895 (0.70×) | 1238 (0.97×) | 1283 (1.00×) | 978 (0.76×) | 722 (0.56×) |
| graph (ophanic arm: partial-edge list plus picture) | small | 451 (1.50×) | 458 (1.51×) | 129 (0.43×) | 302 (1.00×) | 149 (0.50×) | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | 818 (1.29×) | 857 (1.35×) | 211 (0.33×) | 635 (1.00×) | 263 (0.41×) | — |
| graph (ophanic arm: partial-edge list plus picture) | large | 2077 (1.16×) | 2100 (1.17×) | 472 (0.26×) | 1795 (1.00×) | 643 (0.36×) | — |
| containment | small | 355 (2.21×) | 312 (1.94×) | 110 (0.69×) | 161 (1.00×) | 128 (0.80×) | — |
| containment | medium | 512 (1.92×) | 481 (1.80×) | 165 (0.62×) | 268 (1.00×) | 202 (0.75×) | — |
| containment | large | 962 (1.63×) | 957 (1.62×) | 317 (0.54×) | 592 (1.00×) | 404 (0.68×) | — |
| all |  | (1.41×) | (1.31×) | (0.63×) | (1.00×) | (0.66×) | (0.62×) |

### Harness checks

- Calls with an error (left out of scoring; a call with no answer is one): 0
- Empty answers: 0
- Prompts at or over num_ctx (would be truncated): 0
- Answers over 200 characters: 0
- Answers cut off by the token limit: 0
- Settings (harness, framing, stop, max tokens, think): 3, matched, '\n\n', 256, False
- Latency: total 1.6 min, median 0.18 s, max 0.9 s

### All cells

| structure | size | question | ophanic@100 | ophanic@60 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|---|---|
| layout | small | below | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 33% (6–79) n=3 |
| layout | small | right_of | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | small | share | 100% (44–100) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | medium | below | 33% (6–79) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 |
| layout | medium | right_of | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | medium | share | 33% (6–79) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 |
| layout | large | below | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | large | right_of | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | large | share | 0% (0–56) n=3 | 0% (0–56) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | small | no_incoming | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 0% (0–56) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | small | path_length | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | small | reach | 67% (21–94) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | no_incoming | 33% (6–79) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | path_length | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | reach | 67% (21–94) n=3 | 67% (21–94) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | no_incoming | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | path_length | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | reach | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | small | count | 100% (44–100) n=3 | 0% (0–56) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | small | holders | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | small | inside | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | medium | count | 0% (0–56) n=3 | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 0% (0–56) n=3 | — |
| containment | medium | holders | 0% (0–56) n=3 | 33% (6–79) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | — |
| containment | medium | inside | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | large | count | 0% (0–56) n=3 | 0% (0–56) n=3 | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | — |
| containment | large | holders | 33% (6–79) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (44–100) n=3 | 67% (21–94) n=3 | — |
| containment | large | inside | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
# Condition: qwen3:14b (thinking)


**PILOT 3.** This run exists to find harness bugs. Its numbers are descriptive only and test none of DESIGN.md's hypotheses; the confirmatory run uses fresh seeds and 40 structures per cell.

- Run: `pilot3-qwen3-14b`; condition: qwen3:14b (thinking); tasks: 7117-index0.jsonl
- Calls scored: 107; num_ctx: [8192]
- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±5 points.
- Each structure × size cell has 1 structures, each asked 3 questions. The intervals treat every call as independent: they ignore that a structure's three questions are correlated and that the arms are paired on the same structures, so they are too narrow.
- Overall and per-structure percentages mix questions at the floor (see Floors) with questions near the ceiling.

### Hypotheses: the pre-registered statistics (amendments A1-A9, proposed, Kohl to confirm)

**PILOT 3: these numbers test nothing.** They are printed to check that the statistics run, with no reading against any threshold. Intervals are percentile 95% intervals from a cluster bootstrap over structures (2000 replicates, seed 0), resampling within each type × size cell and keeping each structure's arms, questions and models together.

The ophanic arm tested is `ophanic@100`.

**H1a** (layout `right_of` and `below`, medium size): ophanic@100 minus each text arm.

- vs prose: +50.0 points (95% CI +50.0 to +50.0; 1 structures, 2 pairs)
- vs list: +50.0 points (95% CI +50.0 to +50.0; 1 structures, 2 pairs)

**H1b** (layout `share`, medium size): ophanic@100 minus each text arm. `ophanic@60`, whose widths the text arms state, is not in this run: `ophanic@100` stands in, and its widths differ from the stated ones.

- vs prose: —
- vs list: —

**H2** (graph `reach` and `path_length`, all sizes): ophanic@100, here a partial-edge list plus picture (A2), minus json and list.

- vs json: +0.0 points (95% CI +0.0 to +0.0; 3 structures, 6 pairs)
- vs list: +0.0 points (95% CI +0.0 to +0.0; 3 structures, 6 pairs)

**H3** (layout): advantage = ophanic@100 minus the better of prose and list at each size; the statistic is large advantage minus small advantage.

- all layout questions: +0.0 points (95% CI +0.0 to +0.0; 3 structures); advantage by size: small +0.0, medium +50.0, large +0.0.
- spatial only: +0.0 points (95% CI +0.0 to +0.0; 3 structures); advantage by size: small +0.0, medium +50.0, large +0.0.

**H4** (noise, A5): noisy minus clean, against a ±5-point equivalence margin.

- No noise arm paired with ophanic@100 in this run.

**H5** (cost, A6): encoding-only input tokens (each model's own count minus a bare question prompt, unframed), mean of paired per-question ratios by structure type. Primary comparator compact json, then list; indented json for continuity. Threshold 1.5× compact json.

- No `measure_tokens.py` counts for `ophanic@100` in tokens.jsonl: run it to fill this in.

**H6** (construction): **not run.** It is not built, so it is not part of any run until it is built and reviewed (A9).

### Checks from the pilot review

Computed by score.py from calls.jsonl (and tokens.jsonl for the cost table), at Momus's request. Like everything else here, these are descriptive.

#### Layout: spatial questions versus the proportion question

Spatial is `right_of` plus `below`; proportion is `share`. Every arm has to compute the share (A1): the prose, json and list encodings state character widths ("24 of 59 characters"), and the ophanic encodings draw them.

| encoding | layout spatial | layout proportion |
|---|---|---|
| ophanic@100 | 5/5 = 100% (57–100) | — |
| prose | 5/6 = 83% (44–97) | 3/3 = 100% (44–100) |
| json | 5/6 = 83% (44–97) | 3/3 = 100% (44–100) |
| list | 5/6 = 83% (44–97) | 3/3 = 100% (44–100) |
| list-lookup | 5/5 = 100% (57–100) | 3/3 = 100% (44–100) |

#### Proportion answers: the "25" default and a constant-guess baseline

| encoding | share calls | answered exactly 25 | mean absolute error (points) | accuracy |
|---|---|---|---|---|
| ophanic@100 | 0 | 0 | — | — |
| prose | 3 | 0 | 0.6 | 3/3 = 100% (44–100) |
| json | 3 | 0 | 0.6 | 3/3 = 100% (44–100) |
| list | 3 | 0 | 0.6 | 3/3 = 100% (44–100) |
| list-lookup | 3 | 0 | 0.0 | 3/3 = 100% (44–100) |

Gold shares over the 3 share questions: 35 ×2, 55 ×1.
Always answering 25 would score 0/3 = 0% under the ±5 rule; the best constant (30) would score 2/3 = 67%. An ophanic share accuracy at or below that is indistinguishable from a guess, and is no evidence that the model reads widths.

#### Floors: questions every arm got wrong

A question counts here when all of ophanic@100, prose, json, list answered it wrong. A question with no scored answer in some arm (an error, or a call that gave no answer) is left out of the count, so the denominators can be smaller than the structures asked. A11's floor rule: more than half.

| structure | question | wrong in every arm |
|---|---|---|
| layout | below | 0 of 3 |
| layout | right_of | 0 of 2 |
| graph (ophanic arm: partial-edge list plus picture) | no_incoming | 0 of 2 |
| graph (ophanic arm: partial-edge list plus picture) | path_length | 0 of 3 |
| graph (ophanic arm: partial-edge list plus picture) | reach | 0 of 3 |
| containment | count | 0 of 2 |
| containment | holders | 0 of 2 |
| containment | inside | 0 of 3 |

#### Paired: ophanic@100 against each text arm

For the same structure and question: `o+ t−` counts calls ophanic@100 got right and the text arm got wrong; `o− t+` the reverse.

| structure | vs prose: o+ t− / o− t+ | vs json: o+ t− / o− t+ | vs list: o+ t− / o− t+ |
|---|---|---|---|
| layout | 1 / 0 (n=5) | 1 / 0 (n=5) | 1 / 0 (n=5) |
| graph (ophanic arm: partial-edge list plus picture) | 0 / 0 (n=8) | 0 / 0 (n=8) | 0 / 0 (n=8) |
| containment | 0 / 1 (n=7) | 0 / 1 (n=7) | 0 / 1 (n=7) |

### Accuracy by encoding

| encoding | accuracy |
|---|---|
| ophanic@100 | 95% (76–99) n=20 |
| prose | 96% (81–99) n=26 |
| json | 96% (81–99) n=26 |
| list | 96% (82–99) n=27 |
| list-lookup | 100% (68–100) n=8 |

### Encoding × structure

| structure | ophanic@100 | prose | json | list | list-lookup |
|---|---|---|---|---|---|
| layout | 100% (57–100) n=5 | 89% (56–98) n=9 | 89% (56–98) n=9 | 89% (56–98) n=9 | 100% (68–100) n=8 |
| graph (ophanic arm: partial-edge list plus picture) | 100% (68–100) n=8 | 100% (68–100) n=8 | 100% (68–100) n=8 | 100% (70–100) n=9 | — |
| containment | 86% (49–97) n=7 | 100% (70–100) n=9 | 100% (70–100) n=9 | 100% (70–100) n=9 | — |

### Encoding × structure × size

| structure | size | ophanic@100 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|
| layout | small | 100% (34–100) n=2 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | medium | 100% (34–100) n=2 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (34–100) n=2 |
| layout | large | 100% (21–100) n=1 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | small | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | 100% (34–100) n=2 | 100% (34–100) n=2 | 100% (34–100) n=2 | 100% (44–100) n=3 | — |
| containment | small | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | medium | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | large | 0% (0–79) n=1 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |

### Encoding × structure × question kind

| structure | question (kind) | ophanic@100 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|
| layout | below (spatial) | 100% (44–100) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 67% (21–94) n=3 | 100% (34–100) n=2 |
| layout | right_of (spatial) | 100% (34–100) n=2 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| layout | share (proportion) | — | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 |
| graph (ophanic arm: partial-edge list plus picture) | no_incoming (aggregate) | 100% (34–100) n=2 | 100% (34–100) n=2 | 100% (34–100) n=2 | 100% (44–100) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | path_length (path) | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| graph (ophanic arm: partial-edge list plus picture) | reach (path) | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | count (count) | 100% (34–100) n=2 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | holders (containment) | 100% (34–100) n=2 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |
| containment | inside (containment) | 67% (21–94) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | 100% (44–100) n=3 | — |

### Input tokens per encoding

Mean `prompt_eval_count` reported by the model API per call (the prompt as sent: the framing sentence when framing is on, the encoding, the question and instruction, under the model's chat template). The ratio is the mean of each call's count over the json call for the same structure and question.

| structure | size | ophanic@100 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|
| layout | small | 290 (1.01×) | 261 (0.90×) | 290 (1.00×) | 239 (0.82×) | 190 (0.66×) |
| layout | medium | 560 (1.04×) | 493 (0.91×) | 540 (1.00×) | 424 (0.79×) | 330 (0.61×) |
| layout | large | 1142 (1.04×) | 1118 (1.01×) | 1104 (1.00×) | 829 (0.75×) | 637 (0.58×) |
| graph (ophanic arm: partial-edge list plus picture) | small | 460 (1.47×) | 125 (0.40×) | 313 (1.00×) | 147 (0.47×) | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | 791 (1.28×) | 206 (0.33×) | 619 (1.00×) | 257 (0.42×) | — |
| graph (ophanic arm: partial-edge list plus picture) | large | 2470 (1.16×) | 540 (0.25×) | 2136 (1.00×) | 749 (0.35×) | — |
| containment | small | 348 (2.30×) | 103 (0.68×) | 151 (1.00×) | 120 (0.79×) | — |
| containment | medium | 480 (2.03×) | 139 (0.59×) | 237 (1.00×) | 168 (0.71×) | — |
| containment | large | 979 (1.63×) | 317 (0.53×) | 600 (1.00×) | 405 (0.67×) | — |
| all |  | (1.52×) | (0.64×) | (1.00×) | (0.65×) | (0.61×) |

### Harness checks

- Calls with an error (left out of scoring; a call with no answer is one): 10 — json no_incoming ×1, list-lookup below ×1, ophanic@100 count ×1, ophanic@100 holders ×1, ophanic@100 no_incoming ×1, ophanic@100 right_of ×1, ophanic@100 share ×3, prose no_incoming ×1
- Empty answers: 0
- Prompts at or over num_ctx (would be truncated): 0
- Answers over 200 characters: 0
- Answers cut off by the token limit: 0
- Settings (harness, framing, stop, max tokens, think): 3, matched, '', 4096, True
- Latency: total 31.4 min, median 12.43 s, max 74.8 s

### All cells

| structure | size | question | ophanic@100 | prose | json | list | list-lookup |
|---|---|---|---|---|---|---|---|
| layout | small | below | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | small | right_of | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | small | share | — | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | medium | below | 100% (21–100) n=1 | 0% (0–79) n=1 | 0% (0–79) n=1 | 0% (0–79) n=1 | — |
| layout | medium | right_of | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | medium | share | — | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | large | below | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | large | right_of | — | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| layout | large | share | — | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 |
| graph (ophanic arm: partial-edge list plus picture) | small | no_incoming | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | small | path_length | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | small | reach | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | no_incoming | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | path_length | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | medium | reach | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | no_incoming | — | — | — | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | path_length | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| graph (ophanic arm: partial-edge list plus picture) | large | reach | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | small | count | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | small | holders | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | small | inside | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | medium | count | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | medium | holders | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | medium | inside | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | large | count | — | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | large | holders | — | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
| containment | large | inside | 0% (0–79) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | 100% (21–100) n=1 | — |
