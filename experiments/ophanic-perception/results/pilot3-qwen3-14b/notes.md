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
