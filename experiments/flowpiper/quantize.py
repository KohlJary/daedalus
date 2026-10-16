"""Quantize a line's natural speech rhythm onto the sixteenth grid.

Start from where Piper would naturally put each syllable, stretch the line so its last syllable lands
on the rhyme step, then pick one grid step per syllable with a small dynamic program: stay close to the
natural position, keep order, and nudge stressed syllables onto stronger positions (beats, then
eighths) and unstressed ones off the beat.
"""
import numpy as np


def quantize(natural_times, stress, rhyme_step=12, earliest=-2, avg_step=None):
    n = len(natural_times)
    t = np.array(natural_times) - natural_times[0]
    span_nat = t[-1] / avg_step if t[-1] > 0 else n - 1  # natural span in sixteenths
    span = int(np.clip(round(span_nat), n - 1, rhyme_step - earliest))
    ideal = rhyme_step - span + (t / t[-1] if t[-1] > 0 else np.linspace(0, 1, n)) * span

    def weight(step, stressed):
        pos = step % 16
        if stressed:
            return -0.5 if pos % 4 == 0 else (0.0 if pos % 2 == 0 else 0.6)
        return 0.25 if pos % 4 == 0 else 0.0

    steps = list(range(earliest, rhyme_step + 1))
    INF = float("inf")
    cost = {q: (q - ideal[0]) ** 2 + weight(q, stress[0]) for q in steps}
    back = [{}]
    for i in range(1, n):
        new, bk = {}, {}
        for q in steps:
            if i == n - 1 and q != rhyme_step:
                continue
            best, arg = INF, None
            for p, c in cost.items():
                if p < q and c < best:
                    best, arg = c, p
            if arg is not None:
                new[q] = best + (q - ideal[i]) ** 2 + weight(q, stress[i])
                bk[q] = arg
        cost, back = new, back + [bk]
    q = rhyme_step if n > 1 else min(cost, key=cost.get)
    out = [q]
    for i in range(n - 1, 0, -1):
        q = back[i][q]
        out.append(q)
    return out[::-1]
