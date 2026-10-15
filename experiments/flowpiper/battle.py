"""Render a two-MC battle whose rhythms come from real rap (MCFlow).

For each bar of lyrics, find MCFlow bars with the same syllable count and the closest stress pattern,
preferring ones with a rhyme where our rhyme falls and a gap where our phrases break. Inherit their
syllable positions (triplets, rests and all), then render with the duration-override Piper voice.

python battle.py battle.flow     (the score's own rhythm strings are ignored; only bars, voices, words)
"""
import os
import sys
import numpy as np
import pyworld as pw
import soundfile as sf
from scipy.signal import lfilter, butter, sosfilt
from flowpiper import FlowVoice
from grid import SR, BEAT, BAR, SWING
from mcflow import load_bars

SCORE = sys.argv[1] if len(sys.argv) > 1 else "battle.flow"
DRAG, LOOSE = 0.030, 0.007
ACCENT_ST, FALL_ST = 0.6, 3.0
rng = np.random.default_rng(11)
corpus = load_bars(os.environ.get("MCFLOW_DIR", "MCFlow/Humdrum"))


def beat_time(bar, beats):
    """Seconds for a position `beats` into `bar`, with the beat's swing applied inside each eighth."""
    eighth = BEAT / 2
    k, frac = divmod(beats / 0.5, 1.0)
    swung = frac / 0.5 * SWING if frac < 0.5 else SWING + (frac - 0.5) / 0.5 * (1 - SWING)
    return bar * BAR + (k + swung) * eighth


def lowpass(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    return lfilter([1 - a], [1, -a], x)


def contour(audio, sylls, accents, shift):
    x = audio.astype(np.float64)
    f0, sp, ap = pw.wav2world(x, SR, frame_period=5.0)
    fr = lambda smp: min(len(f0), int(smp / SR * 200))
    semis = np.full(len(f0), shift)
    for k, s in enumerate(sylls):
        a, b = fr(s["vowel_sample"]), fr(s["end_sample"])
        if b <= a:
            continue
        if accents[k]:
            semis[a:b] += ACCENT_ST * np.hanning(b - a)
        if k == len(sylls) - 1:
            semis[a:b] -= np.linspace(0, FALL_ST, b - a)
    f0 = np.where(f0 > 0, f0 * 2 ** (semis / 12), 0)
    out = pw.synthesize(f0, sp, ap, SR, frame_period=5.0)
    return np.pad(out, (0, max(0, len(audio) - len(out))))[: len(audio)]


# ---- read the score: voices and lines grouped by bar ----
bars, voice = {}, None
for raw in open(SCORE, encoding="utf-8"):
    line = raw.split("#", 1)[0].strip()
    if not line:
        continue
    if line.startswith("@"):
        _, vpath, spk, pan, shift = line.split()
        voice = (vpath, int(spk), float(pan), float(shift))
        continue
    head, words = line.split("|", 1)
    bar = int(head.split()[0].split(".")[0])
    bars.setdefault(bar, []).append((voice, words.strip()))

voices = {}
used = set()
beat_audio, _ = sf.read("beat.wav")
vox = np.zeros((len(beat_audio), 2))
transcript, report = [], []

def score(info, tb):
    stress, breaks, n, rhyme_idx = info["stress"], info["breaks"], info["n"], info["rhyme_idx"]
    syl = tb["syl"]
    cost = sum(a != b["stress"] for a, b in zip(stress, syl))
    cost += 0 if syl[rhyme_idx]["rhyme"] else 2.0
    for b in breaks:
        if 0 < b < n:
            gap = syl[b]["pos"] - (syl[b - 1]["pos"] + syl[b - 1]["dur"])
            cost += 0 if gap > 0.01 or syl[b]["brk"] not in (".", "0", "1") else 0.75
    return cost


# our syllables per bar: stress, where phrases break, where the rhyme sits
info = {}
for bar in sorted(bars):
    chunks = bars[bar]
    vkey = chunks[0][0]
    if vkey[:2] not in voices:
        voices[vkey[:2]] = FlowVoice(vkey[0], vkey[1])
        voices[vkey[:2]].scales[0] = 0.45  # less sampling noise: cleaner, more legible
    fv = voices[vkey[:2]]
    stress, breaks, sizes = [], set(), []
    for _, words in chunks:
        sy = fv.syllables(fv.tokens(words)[1])
        stress += [1 if s["stress"] else 0 for s in sy]
        sizes.append(len(sy))
        breaks.add(len(stress))
    n = len(stress)
    info[bar] = {"chunks": chunks, "fv": fv, "stress": stress, "breaks": breaks, "sizes": sizes, "n": n,
                 "rhyme_idx": max(i for i, s in enumerate(stress) if s) if any(stress) else n - 1}

# one rapper per MC, so each verse keeps one coherent flow: the rapper whose bars fit best overall
by_mc = {}
for bar in sorted(bars):
    by_mc.setdefault(info[bar]["chunks"][0][0][:2], []).append(bar)
artists = sorted({b["mc"] for b in corpus})
choice, taken = {}, set()
for vk, mc_bars in by_mc.items():
    best_artist, best_total, best_pick = None, float("inf"), None
    for artist in artists:
        if artist in taken:
            continue
        pool = [i for i, b in enumerate(corpus) if b["mc"] == artist]
        pick, total, ok = {}, 0.0, True
        for bar in mc_bars:
            cands = [i for i in pool if len(corpus[i]["syl"]) == info[bar]["n"] and i not in pick.values()]
            if not cands:
                ok = False
                break
            i = min(cands, key=lambda i: score(info[bar], corpus[i]))
            pick[bar] = i
            total += score(info[bar], corpus[i])
        if ok and total < best_total:
            best_artist, best_total, best_pick = artist, total, pick
    if best_artist is None:
        raise SystemExit(f"no single rapper covers every bar for voice {vk}")
    taken.add(best_artist)
    choice.update(best_pick)
    print(f"voice {vk[1]}: flow from {best_artist} (fit cost {best_total:.1f} over {len(mc_bars)} bars)")

for bar in sorted(bars):
    chunks, fv, sizes, n = info[bar]["chunks"], info[bar]["fv"], info[bar]["sizes"], info[bar]["n"]
    best = corpus[choice[bar]]
    tmpl = best["syl"]

    # render each phrase with the template's positions
    k0 = 0
    for (vk, words), size in zip(chunks, sizes):
        _, spk, pan, shift = vk
        part = tmpl[k0:k0 + size]
        times = [beat_time(bar, s["pos"]) + DRAG + rng.normal(0, LOOSE) for s in part]
        for k in range(1, len(times)):
            times[k] = max(times[k], times[k - 1] + 0.045)
        last = part[-1]
        hold = max(0.12, beat_time(bar, last["pos"] + last["dur"]) - beat_time(bar, last["pos"]))
        accents = [bool(s["stress"]) for s in part]
        audio, t0, sylls = fv.render(words, times, hold)
        audio = contour(audio, sylls, accents, shift)
        gain = np.ones(len(audio))
        for j, s in enumerate(sylls):
            a, b = s["vowel_sample"], min(len(audio), s["end_sample"])
            if accents[j] and b > a:
                gain[a:b] = np.maximum(gain[a:b], 1 + 0.35 * np.hanning(b - a))
        audio *= gain
        i = int(round(t0 * SR))
        l, r = np.cos((pan + 1) * np.pi / 4) * 1.41, np.sin((pan + 1) * np.pi / 4) * 1.41
        seg = audio[: len(vox) - i]
        vox[i:i + len(seg), 0] += seg * l
        vox[i:i + len(seg), 1] += seg * r
        transcript.append((times[0], bar, spk, words))
        k0 += size
    grid = " ".join(f"{s['pos']:.2f}{'*' if s['stress'] else ''}{'R' if s['rhyme'] else ''}" for s in tmpl)
    report.append(f"bar {bar:>2}: {n:>2} syl <- {best['mc']}, {best['song']} @ {best['tempo']:.0f} BPM | {grid}")

# ---- mix ----
def peaking(x, f0, gain_db, q):
    """RBJ peaking EQ."""
    A, w = 10 ** (gain_db / 40), 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = [1 + al * A, -2 * np.cos(w), 1 - al * A]
    a = [1 + al / A, -2 * np.cos(w), 1 - al / A]
    return lfilter(np.array(b) / a[0], np.array(a) / a[0], x)


def compress(x, thresh_db=-20, ratio=3.5, attack=0.004, release=0.09):
    level = np.abs(x)
    env = np.zeros_like(x)
    aa, ar = np.exp(-1 / (attack * SR)), np.exp(-1 / (release * SR))
    e = 0.0
    for i, v in enumerate(level):
        e = aa * e + (1 - aa) * v if v > e else ar * e + (1 - ar) * v
        env[i] = e
    peak = np.max(env) + 1e-9
    db = 20 * np.log10(env / peak + 1e-9)
    over = np.maximum(0, db - thresh_db)
    return x * 10 ** (-(over - over / ratio) / 20)


def battle_mic(x):
    """Cupped, too-close mic, kept light: thin the lows, honk the mids, dull the air, squash a bit."""
    x = sosfilt(butter(2, 130, "highpass", fs=SR, output="sos"), x)
    x = peaking(x, 250, -2.0, 1.0)     # clear the mud the low voices and the bass fight over
    x = peaking(x, 1300, 4.0, 0.9)     # the cupped honk
    x = peaking(x, 3200, 2.5, 1.2)     # consonant presence so the words read
    x = sosfilt(butter(2, 7000, "lowpass", fs=SR, output="sos"), x)
    x = compress(x)
    return np.tanh(x / (np.max(np.abs(x)) + 1e-9) * 1.3)


def plate(length=0.9, seed=0):
    r = np.random.default_rng(seed)
    n = int(length * SR)
    t = np.arange(n) / SR
    ir = r.standard_normal(n) * np.exp(-6.9 * t / length)
    ir = sosfilt(butter(2, [300, 5000], "bandpass", fs=SR, output="sos"), ir)
    ir = np.concatenate([np.zeros(int(0.022 * SR)), ir])  # pre-delay
    return ir / np.sqrt((ir ** 2).sum())


dry = np.stack([battle_mic(vox[:, c]) for c in (0, 1)], 1)
mono = dry.mean(1)
wet = np.stack([np.convolve(mono, plate(seed=c))[: len(mono)] for c in (0, 1)], 1)
vox = dry + 0.14 * wet / (np.max(np.abs(wet)) + 1e-9) * np.max(np.abs(dry))
beat_rms = np.sqrt((beat_audio ** 2).mean())
active = np.abs(vox) > 0.02
vox *= (beat_rms * 1.7) / (np.sqrt((vox[active] ** 2).mean()) + 1e-9)
env = np.convolve(np.abs(vox).mean(1), np.ones(220) / 220, "same")
duck = 1 - 0.5 * np.clip(env / (env.max() + 1e-9) * 2.5, 0, 1)
low = np.stack([lowpass(beat_audio[:, c], 220) for c in (0, 1)], 1)
mix = low * (0.5 + 0.5 * duck[:, None]) + (beat_audio - low) * duck[:, None] + vox
mix /= np.max(np.abs(mix)) * 1.05
out = SCORE.rsplit(".", 1)[0] + "_mcflow"
sf.write(f"{out}.wav", mix, SR)

names = {174: "Hotfix", 90: "Coverage"}
lines = ["# Transcript", "", "| Time | Bar | MC | Words |", "| --- | --- | --- | --- |"]
for t, bar, spk, words in transcript:
    lines.append(f"| {int(t // 60)}:{t % 60:04.1f} | {bar} | {names.get(spk, spk)} | {words} |")
lines += ["", "## Rhythm sources", "", "Each bar's timing is borrowed from a real bar in MCFlow "
          "(position in beats; * stressed, R rhymed).", ""] + [f"- {r}" for r in report]
open(f"{out}_transcript.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(report))
