"""Shared timing grid for the beat and the vocal."""
SR = 22050
BPM = 94
BEAT = 60 / BPM
BAR = 4 * BEAT
SWING = 0.62  # share of an eighth note given to its first sixteenth (G-funk sits around 60-64%)
N_BARS = 19   # 2 intro + 16 battle + 1 outro
VERSE_START_BAR = 2


def sixteenth_time(bar, step):
    """Seconds from the top of the song to sixteenth `step` (may exceed 15) of `bar`, swung."""
    bar += step // 16
    step %= 16
    eighth = BEAT / 2
    t = bar * BAR + (step // 2) * eighth
    if step % 2:
        t += SWING * eighth
    return t
