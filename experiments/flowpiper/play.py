"""Play a rap score (verse.flow) over beat.wav.

Each score line is one unbroken phrase: where it starts, a rhythm string, and the words.
Timing sits a little behind the beat with some human looseness; pitch gets a lift on accented
syllables and a fall at phrase ends (WORLD vocoder); the mix carves room so the words read.
"""
import os
import sys
import numpy as np
import pyworld as pw
import soundfile as sf
from scipy.signal import lfilter
from flowpiper import FlowVoice
from grid import SR, sixteenth_time

SCORE = sys.argv[1] if len(sys.argv) > 1 else "verse.flow"
DRAG = 0.030        # seconds behind the beat: the G-funk lean
LOOSE = 0.007       # human timing spread (std dev, seconds)
ACCENT_ST = 0.6     # semitones of lift on accented syllables (small: big lifts sound cheerful)
DROP_ST = -2.5      # whole voice pitched down: heavier, meaner
FALL_ST = 3.5       # semitones of fall across a phrase's last syllable: lands like a statement
rng = np.random.default_rng(3)


def parse(path):
    for raw in open(path, encoding="utf-8"):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("@"):  # voice switch: @ path speaker pan shift
            _, vpath, spk, pan, shift = line.split()
            yield "voice", (vpath, int(spk), float(pan), float(shift)), None
            continue
        head, words = line.split("|", 1)
        pos, rhythm = head.split()
        bar, step = (int(p) for p in pos.split("."))
        yield bar * 16 + step, rhythm, words.strip()


def abs_time(abs_step):
    return sixteenth_time(abs_step // 16, abs_step % 16)


def lowpass(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    return lfilter([1 - a], [1, -a], x)


def contour(audio, sylls, accents):
    """Bend pitch: lift accented syllables, fall across the last one."""
    x = audio.astype(np.float64)
    f0, sp, ap = pw.wav2world(x, SR, frame_period=5.0)
    fr = lambda smp: min(len(f0), int(smp / SR * 1000 / 5.0))
    semis = np.full(len(f0), CUR_SHIFT)
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


voices = {}
fv = FlowVoice(os.environ.get("FLOWPIPER_VOICE", "voices/en-us-ryan-high.onnx"))
CUR_SHIFT, CUR_PAN, CUR_NAME = DROP_ST, 0.0, "ryan"
beat, _ = sf.read("beat.wav")
vox = np.zeros((len(beat), 2))
print("start  syl  worst_ms  tight  words")
transcript = []
for start, rhythm, words in parse(SCORE):
    if start == "voice":
        vpath, spk, CUR_PAN, CUR_SHIFT = rhythm
        if (vpath, spk) not in voices:
            voices[(vpath, spk)] = FlowVoice(vpath, spk)
        fv, CUR_NAME = voices[(vpath, spk)], f"speaker {spk}"
        continue
    onsets = [start + i for i, c in enumerate(rhythm) if c in "Xx"]
    accents = [c == "X" for c in rhythm if c in "Xx"]
    n_syl = len(fv.syllables(fv.tokens(words)[1]))
    if n_syl != len(onsets):
        raise SystemExit(f"{words!r}: Piper hears {n_syl} syllables, rhythm has {len(onsets)}")
    last_x = max(i for i, c in enumerate(rhythm) if c in "Xx")
    hold = abs_time(start + len(rhythm)) - abs_time(start + last_x)
    times = [abs_time(q) + DRAG + rng.normal(0, LOOSE) for q in onsets]
    for k in range(1, len(times)):  # looseness never reorders syllables
        times[k] = max(times[k], times[k - 1] + 0.05)
    audio, t0, sylls = fv.render(words, times, hold)
    audio = contour(audio, sylls, accents)
    gain = np.ones(len(audio))
    for k, s in enumerate(sylls):
        a, b = s["vowel_sample"], min(len(audio), s["end_sample"])
        if accents[k] and b > a:
            gain[a:b] = np.maximum(gain[a:b], 1 + 0.35 * np.hanning(b - a))  # accents punch with level, not pitch
    audio = audio * gain
    i = int(round(t0 * SR))
    l, r = np.cos((CUR_PAN + 1) * np.pi / 4), np.sin((CUR_PAN + 1) * np.pi / 4)
    seg = audio[: len(vox) - i]
    vox[i:i + len(seg), 0] += seg * l * 1.41
    vox[i:i + len(seg), 1] += seg * r * 1.41
    err = [abs((i + s["vowel_sample"]) / SR - t) * 1000 for s, t in zip(sylls, times)]
    transcript.append((times[0], start, words, CUR_NAME))
    print(f"{start // 16}.{start % 16:<4} {len(onsets):>3}  {max(err):>7.1f}  {len(fv.tight):>5}   {words}")

# vocal chain: high-pass ~85 Hz, presence lift around 2-5 kHz, light saturation
vox = np.stack([vox[:, c] - lowpass(vox[:, c], 85) for c in (0, 1)], 1)
vox = np.stack([vox[:, c] + 0.5 * (lowpass(vox[:, c], 5500) - lowpass(vox[:, c], 1800)) for c in (0, 1)], 1)
vox = np.tanh(vox / (np.max(np.abs(vox)) + 1e-9) * 1.15)
beat_rms = np.sqrt((beat ** 2).mean())
active = np.abs(vox) > 0.02  # (stereo: both channels count)
vox *= (beat_rms * 1.7) / (np.sqrt((vox[active] ** 2).mean()) + 1e-9)

# sidechain: dip the beat's mids up to 6 dB under the voice, keep most of its lows
env = np.convolve(np.abs(vox).mean(1), np.ones(220) / 220, "same")
duck = 1 - 0.5 * np.clip(env / (env.max() + 1e-9) * 2.5, 0, 1)
beat_low = np.stack([lowpass(beat[:, c], 220) for c in (0, 1)], 1)
beat_high = beat - beat_low
mix = beat_low * (0.5 + 0.5 * duck[:, None]) + beat_high * duck[:, None] + vox
mix /= np.max(np.abs(mix)) * 1.05
OUT = SCORE.rsplit(".", 1)[0]
sf.write(f"{OUT}.wav", mix, SR)

# transcript: one line per bar, with the time each phrase starts
lines = ["# Transcript", "", "| Time | Bar | Voice | Words |", "| --- | --- | --- | --- |"]
for t, start, words, who in transcript:
    stamp = f"{int(t // 60)}:{t % 60:04.1f}"
    lines.append(f"| {stamp} | {start // 16}.{start % 16} | {who} | {words} |")
open(f"{OUT}_transcript.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
sf.write(f"{OUT}_vocal.wav", vox / (np.max(np.abs(vox)) * 1.05), SR)
