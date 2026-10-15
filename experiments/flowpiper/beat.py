"""G-funk beat synthesized from scratch with numpy. No samples.

Moog-style bass (detuned saws through a resonant 4-pole ladder with a per-note filter envelope and
slides), a punchy swung kit with ghost notes and open hats, Rhodes stabs instead of a pad, and the
high whining portamento lead. Writes beat.wav.
"""
import numpy as np
import soundfile as sf
from grid import SR, BAR, sixteenth_time, N_BARS

rng = np.random.default_rng(7)
total = int(SR * BAR * N_BARS + SR * 2)
mix = np.zeros((total, 2))


def place(sig, t, gain=1.0, pan=0.0):
    i = int(t * SR)
    if i >= total:
        return
    j = min(total, i + len(sig))
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    mix[i:j, 0] += sig[: j - i] * gain * l
    mix[i:j, 1] += sig[: j - i] * gain * r


def env(n, a, d):
    t = np.arange(n) / SR
    e = np.exp(-t / d)
    na = max(1, int(a * SR))
    e[:na] *= np.linspace(0, 1, na)
    return e


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def onepole_lp(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def room(x, mix_amt=0.25):
    """Cheap short room: a few feedback combs, for snare and clap tails."""
    out = np.zeros(len(x) + int(0.3 * SR))
    out[: len(x)] += x
    for d_ms, g in [(23, 0.5), (31, 0.45), (37, 0.4), (43, 0.35)]:
        d = int(d_ms * SR / 1000)
        buf = np.zeros(len(out))
        buf[: len(x)] = x
        for i in range(d, len(buf)):
            buf[i] += g * buf[i - d]
        out += buf * mix_amt / 4
    return out


# ---------- drums ----------
def kick():
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    f = 45 + 120 * np.exp(-t / 0.03)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.001, 0.22)
    click = onepole_lp(rng.standard_normal(n), 3000) * env(n, 0.0005, 0.006) * 0.8
    return np.tanh((body + click) * 2.2) * 0.9


def snare(ghost=False):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - onepole_lp(noise, 1200)          # keep the crack, lose the rumble
    noise = onepole_lp(noise, 7000)
    tone = (np.sin(2 * np.pi * 185 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)) * env(n, 0.001, 0.04)
    s = noise * env(n, 0.001, 0.07 if not ghost else 0.03) * 0.9 + tone * 0.7
    return np.tanh(s * 1.5) * (0.35 if ghost else 1.0)


def clap():
    n = int(0.2 * SR)
    noise = rng.standard_normal(n)
    noise = onepole_lp(noise - onepole_lp(noise, 900), 5000)
    e = np.zeros(n)
    for k, off in enumerate([0, 0.009, 0.019]):
        i = int(off * SR)
        e[i:] += env(n - i, 0.0005, 0.007 if k < 2 else 0.06)
    return noise * e


def hat(open_=False):
    n = int((0.22 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    # metallic: a few square-ish partials plus noise, high-passed
    metal = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in [3140, 4410, 5210, 6370]) / 4
    x = metal * 0.5 + rng.standard_normal(n) * 0.5
    x = x - onepole_lp(x, 6000)
    return x * env(n, 0.0005, 0.07 if open_ else 0.012)


# ---------- bass ----------
def moog_bass(notes, length, cutoff=150, env_amt=1400, env_decay=0.09, res=0.7):
    """notes: (start_s, dur_s, midi, slide_into). Detuned saws -> 4-pole resonant ladder."""
    n = int(length * SR)
    target = np.full(n, np.nan)
    gate = np.zeros(n)
    fenv = np.zeros(n)
    for start, dur, m, slide in notes:
        a, b = int(start * SR), min(n, int((start + dur) * SR))
        target[a:b] = hz(m)
        g = np.ones(b - a)
        rel = min(len(g), int(0.012 * SR))
        g[-rel:] = np.linspace(1, 0, rel)
        gate[a:b] = np.maximum(gate[a:b], g)
        if not slide:
            fenv[a:b] = np.maximum(fenv[a:b], np.exp(-np.arange(b - a) / SR / env_decay))
    # hold pitch through rests so slides start from the last note
    last = hz(notes[0][2])
    freq = np.empty(n)
    slide_alpha = 1 - np.exp(-1 / (0.045 * SR))
    cur = last
    slides = {int(s * SR) for s, _, _, sl in notes if sl}
    in_slide = False
    for i in range(n):
        tgt = target[i] if not np.isnan(target[i]) else cur
        if i in slides:
            in_slide = True
        if np.isnan(target[i]):
            in_slide = False
        if in_slide:
            cur += slide_alpha * (tgt - cur)
        else:
            cur = tgt
        freq[i] = cur
    ph1 = np.cumsum(freq) / SR
    ph2 = np.cumsum(freq * 1.006) / SR
    osc = (2 * (ph1 % 1) - 1) + (2 * (ph2 % 1) - 1) * 0.8 + np.sin(2 * np.pi * ph1 * 0.5) * 0.6
    # ladder filter (simplified Huovilainen with tanh)
    fc = np.clip(cutoff + env_amt * fenv, 40, 8000)
    gcoef = 1 - np.exp(-2 * np.pi * fc / SR)
    y = np.zeros(n)
    s = [0.0, 0.0, 0.0, 0.0]
    for i in range(n):
        x = np.tanh(osc[i] - 4 * res * s[3])
        g_ = gcoef[i]
        s[0] += g_ * (x - s[0])
        s[1] += g_ * (s[0] - s[1])
        s[2] += g_ * (s[1] - s[2])
        s[3] += g_ * (s[2] - s[3])
        y[i] = s[3]
    return np.tanh(y * gate * 3.2)


# ---------- keys and lead ----------
def rhodes_stab(midis, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for m in midis:
        f = hz(m)
        mod = np.sin(2 * np.pi * f * 1.003 * t) * 0.9 * np.exp(-t / 0.06)
        out += np.sin(2 * np.pi * f * t + mod) * np.exp(-t / 0.35)
    rel = int(0.03 * SR)
    out[-rel:] *= np.linspace(1, 0, rel)
    # a little tremolo, very Rhodes
    return out / len(midis)


def whine(notes, length, glide=0.14, vib=0.014):
    """The G-funk lead: high sine/triangle with long portamento and delayed vibrato."""
    n = int(length * SR)
    t = np.arange(n) / SR
    target = np.zeros(n)
    for off, m in notes:
        target[t >= off] = hz(m)
    alpha = 1 - np.exp(-1 / (glide * SR))
    f = np.empty(n)
    cur = target[0]
    for i in range(n):
        cur += alpha * (target[i] - cur)
        f[i] = cur
    vib_on = np.clip((t - 0.2) / 0.4, 0, 1)
    f = f * (1 + vib * vib_on * np.sin(2 * np.pi * 5.8 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = np.sin(ph) + 0.12 * np.sin(3 * ph) + 0.04 * np.sin(5 * ph)
    e = np.ones(n)
    e[: int(0.08 * SR)] = np.linspace(0, 1, int(0.08 * SR))
    e[-int(0.1 * SR):] *= np.linspace(1, 0, int(0.1 * SR))
    return s * e


# ---------- arrangement ----------
CHORDS = [[41, 53, 56, 60], [42, 54, 58, 61]]          # Fm, then Gb (the flat-II: menace)
STABS = [(0, 3), (6, 1), (10, 2), (14, 1)]              # (sixteenth, length in sixteenths)
BASS = [  # (sixteenth, length, midi, slide_into): Fm bar, then Gb bar
    [(0, 3, 29, False), (3, 1, 29, False), (6, 2, 41, False), (8, 2, 29, True), (11, 1, 30, False), (12, 3, 29, True)],
    [(0, 3, 30, False), (3, 1, 30, False), (6, 2, 42, False), (8, 2, 30, True), (11, 1, 29, False), (14, 2, 28, True)],
]
LEAD = [  # half steps and a tritone: the whine turns eerie
    [(0, 84), (4, 85), (8, 84), (12, 79)],
    [(0, 84), (6, 85), (10, 78), (12, 79)],
]
KICKS = [[0, 6, 10], [0, 3, 6, 10, 13]]

step_len = sixteenth_time(0, 2) / 2  # average sixteenth, for note lengths
for bar in range(N_BARS):
    t0 = bar * BAR
    intro = bar < 2
    outro = bar >= N_BARS - 1
    # kit
    if not (intro and bar == 0):
        for s in KICKS[bar % 2]:
            place(kick(), sixteenth_time(bar, s), 0.9)
    for s in [4, 12]:
        place(room(snare()), sixteenth_time(bar, s), 0.55)
        place(room(clap(), 0.35), sixteenth_time(bar, s) + 0.004, 0.3, 0.1)
    for s in ([7, 15] if bar % 2 else [15]):
        place(snare(ghost=True), sixteenth_time(bar, s), 0.4, -0.1)
    for s in range(16):
        if s in (6, 14):
            place(hat(True), sixteenth_time(bar, s), 0.09, 0.35)
        else:
            accent = 0.08 if s % 4 == 2 else (0.06 if s % 2 == 0 else 0.035)
            place(hat(), sixteenth_time(bar, s), accent, 0.35)
    # keys: stabs, not a pad
    chord = CHORDS[(bar // 2) % 2]
    for s, ln in STABS:
        place(rhodes_stab(chord, ln * step_len + 0.05), sixteenth_time(bar, s), 0.42, -0.3)
    # bass
    if not intro or bar == 1:
        phrase = BASS[bar % 2]
        notes = [(sixteenth_time(bar, s) - t0, ln * step_len * 0.95, m, sl) for s, ln, m, sl in phrase]
        place(moog_bass(notes, BAR + 0.1), t0, 0.6)
    # lead whine: intro, every fourth bar, outro
    if intro or outro or bar % 4 == 3:
        phrase = LEAD[bar % 2]
        notes = [(sixteenth_time(bar, s) - t0, m) for s, m in phrase]
        place(whine(notes, BAR), t0, 0.22 if not intro else 0.3, 0.3)

# bus: glue and a touch of saturation
peak = np.max(np.abs(mix))
mix = np.tanh(mix / peak * 1.4) * 0.8
sf.write("beat.wav", mix, SR)
print("beat.wav", round(len(mix) / SR, 2), "s")
