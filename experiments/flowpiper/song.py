"""Put the verse on the beat, rhyme on beat 4.

python song.py straight   - one syllable per sixteenth
python song.py quantized  - Piper's natural rhythm snapped to the grid (default)
"""
import os
import sys
import numpy as np
import soundfile as sf
from flowpiper import FlowVoice
from grid import SR, BAR, VERSE_START_BAR, sixteenth_time
from quantize import quantize

MODE = sys.argv[1] if len(sys.argv) > 1 else "quantized"
AVG_STEP = BAR / 16

RHYME_STEP = 12   # beat 4
HOLD_STEPS = 2    # the rhyme rings for two sixteenths, leaving room for a pickup

fv = FlowVoice(os.environ.get("FLOWPIPER_VOICE", "voices/en-us-ryan-high.onnx"))
beat, _ = sf.read("beat.wav")
vox = np.zeros(len(beat))
report = []

for n, line in enumerate(open("verse.txt").read().splitlines()):
    bar = VERSE_START_BAR + n
    syl_count = len(fv.syllables(fv.tokens(line)[1]))
    if syl_count > 15:
        raise SystemExit(f"line {n + 1} has {syl_count} syllables; max is 15")
    if MODE == "straight":
        steps = [RHYME_STEP - (syl_count - 1) + k for k in range(syl_count)]
    else:
        runs = [fv.natural(line) for _ in range(3)]  # the duration predictor is stochastic: average it
        nat = np.mean([r[0] for r in runs], axis=0)
        steps = quantize(list(nat), runs[0][1], RHYME_STEP, -2, AVG_STEP)
    times = [sixteenth_time(bar, q) if q >= 0 else sixteenth_time(bar - 1, 16 + q) for q in steps]
    hold = sixteenth_time(bar, RHYME_STEP + HOLD_STEPS) - sixteenth_time(bar, RHYME_STEP)
    audio, t0, sylls = fv.render(line, times, hold)

    # emphasis: stressed syllables a little hotter, the rhyme hotter still
    gain = np.ones(len(audio))
    for k, s in enumerate(sylls):
        boost = 1.5 if k == len(sylls) - 1 else (1.3 if s["stress"] else 1.0)
        a, b = s["vowel_sample"], min(len(audio), s["end_sample"])
        if b > a and boost > 1:
            ramp = np.hanning(b - a) * (boost - 1) + 1
            gain[a:b] = np.maximum(gain[a:b], ramp)
    audio = audio * gain

    i = int(round(t0 * SR))
    vox[i:i + len(audio)] += audio[: len(vox) - i]
    # timing check: where each vowel actually landed vs the grid
    err = [abs((i + s["vowel_sample"]) / SR - t) * 1000 for s, t in zip(sylls, times)]
    report.append((n + 1, syl_count, round(max(err), 1), " ".join(map(str, steps))))

# vocal chain: high-pass, gentle saturation, level against the beat
vox = vox - np.convolve(vox, np.ones(256) / 256, "same")  # ~85 Hz high-pass, keeps the voice fundamental
vox = np.tanh(vox / (np.max(np.abs(vox)) + 1e-9) * 1.8)
beat_rms = np.sqrt((beat ** 2).mean())
active = np.abs(vox) > 0.02
vox *= (beat_rms * 1.5) / (np.sqrt((vox[active] ** 2).mean()) + 1e-9)

# light sidechain: dip the beat 3 dB where the vocal is loud
env = np.convolve(np.abs(vox), np.ones(400) / 400, "same")
duck = 1 - 0.3 * np.clip(env / (env.max() + 1e-9) * 2, 0, 1)
mix = beat * duck[:, None] + vox[:, None]
mix /= np.max(np.abs(mix)) * 1.05
sf.write(f"hit_em_up_{MODE}.wav", mix, SR)
sf.write(f"vocal_only_{MODE}.wav", vox / (np.max(np.abs(vox)) * 1.05), SR)

print(MODE, "- line, syllables, worst vowel offset from grid (ms), steps")
for r in report:
    print(*r)
