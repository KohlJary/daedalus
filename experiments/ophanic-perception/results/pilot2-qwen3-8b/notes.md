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
