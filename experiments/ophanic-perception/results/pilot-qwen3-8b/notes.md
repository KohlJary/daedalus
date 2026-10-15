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
