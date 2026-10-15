# PILOT: no hypothesis tested

**PILOT.** This run exists to find harness bugs. Its numbers are descriptive only and test none of DESIGN.md's hypotheses; the confirmatory run uses fresh seeds and 40 structures per cell.

- Run: `pilot-qwen3-8b`; model(s): qwen3:8b; tasks: 1015.jsonl
- Calls scored: 1485; num_ctx: [10240]
- Cells show accuracy, the Wilson 95% interval, and n. Proportions are scored within ±5 points.

## What the pilot was for, and what it found

The pilot ran qwen3:8b (Ollama 0.12.7, `think: false`, temperature 0, num_ctx 10240, num_predict 128) on seed
1015. That's 10 structures per type and size, 3 questions each, and 5 encodings (ophanic@100, ophanic@60, prose,
json, list), plus ophanic-noise@100 on the even-indexed structures: 1,485 calls in 6.6 minutes. ComfyUI stayed up.

**Harness.**
- No call errored, and none came back empty or over num_ctx.
- Every gold answer is rederived from the json encoding by an independent solver in `test_generate.py`. Spot-checks
  of the cases where every encoding disagreed with the gold found the gold right.
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

