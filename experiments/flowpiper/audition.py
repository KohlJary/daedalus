"""Rank LibriTTS speakers by pitch: median f0 and how much it moves (more movement, more expressive)."""
import os
import numpy as np, onnxruntime as ort, pyworld as pw
VOICE = os.environ.get("FLOWPIPER_MULTI_VOICE", "voices/en-us-libritts-high.onnx")
from piper import PiperVoice
v = PiperVoice.load(VOICE)
sess = ort.InferenceSession(VOICE)
ids = v.phonemes_to_ids([p for s in v.phonemize("Your pipeline is so long it qualifies for a pension, and I am done waiting.") for p in s])
x = np.array([ids], dtype=np.int64); L = np.array([len(ids)], dtype=np.int64)
rows = []
for sid in range(0, 904, 6):
    a = sess.run(None, {'input': x, 'input_lengths': L, 'scales': np.array([0.667, 1, 0.8], np.float32), 'sid': np.array([sid], np.int64)})[0].squeeze().astype(np.float64)
    f0, t = pw.dio(a, 22050); f0 = pw.stonemask(a, f0, t, 22050); f = f0[f0 > 0]
    if len(f) > 20:
        rows.append((sid, float(np.median(f)), float(np.std(12 * np.log2(f / np.median(f)))), float(np.sqrt((a ** 2).mean()))))
rows.sort(key=lambda r: r[1])
print("sid median_f0 pitch_spread_semitones rms")
for r in rows[:25]:
    print(r[0], round(r[1]), round(r[2], 2), round(r[3], 3))
