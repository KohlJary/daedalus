"""Flow for Piper: put every syllable's vowel on a beat grid by overriding VITS phoneme durations.

Needs the *.predict.onnx and *.flow.onnx variants made by flowpiper_build.py.
"""
import numpy as np
import onnxruntime as ort
from piper import PiperVoice

VOWELS = set("aeiouyæɐɑɒɔəɚɛɜɝɪʊʌᵻɘɵɨʉøɯɤœɶʏ")
SKIP = set("ˈˌ .,!?;:'\"-^$_")
HOP = 256  # samples per duration frame


class FlowVoice:
    def __init__(self, onnx_path, speaker=None):
        self.voice = PiperVoice.load(onnx_path)
        self.sr = self.voice.config.sample_rate
        self.fps = self.sr / HOP
        self.inv = {i: s for s, ids in self.voice.config.phoneme_id_map.items() for i in ids}
        opts = ort.SessionOptions()
        self.predict = ort.InferenceSession(onnx_path.replace(".onnx", ".predict.onnx"), opts)
        self.flow = ort.InferenceSession(onnx_path.replace(".onnx", ".flow.onnx"), opts)
        self.scales = np.array([0.6, 1.0, 0.8], dtype=np.float32)
        self.extra = {}
        if any(i.name == "sid" for i in self.flow.get_inputs()):
            self.extra = {"sid": np.array([speaker or 0], dtype=np.int64)}

    def tokens(self, text):
        phonemes = [p for sent in self.voice.phonemize(text) for p in sent]
        ids = self.voice.phonemes_to_ids(phonemes)
        x = np.array([ids], dtype=np.int64)
        L = np.array([len(ids)], dtype=np.int64)
        _, w = self.predict.run(None, {"input": x, "input_lengths": L, "scales": self.scales, **self.extra})
        return ids, [self.inv[i] for i in ids], w[0, 0].astype(float)

    def syllables(self, syms):
        """Group symbol positions into syllables: onset consonants, vowel nucleus, coda consonants.
        Returns list of dicts with token indices and whether the syllable carries primary stress."""
        sylls, onset, stress, word_start = [], [], False, True
        i = 0
        n = len(syms)
        while i < n:
            s = syms[i]
            if s == "_" or s in "^$":
                i += 1
                continue
            if s == "ˈ":
                stress = True
                i += 1
                continue
            if s in SKIP:
                if s == " " and sylls and onset:  # word-final consonants become the last syllable's coda
                    sylls[-1]["coda"] += onset
                    onset = []
                i += 1
                continue
            if s in VOWELS or s == "ː":
                nuc = []
                while i < n and (syms[i] in VOWELS or syms[i] in "ː_"):
                    if syms[i] != "_":
                        nuc.append(i)
                    i += 1
                sylls.append({"onset": onset, "nucleus": nuc, "coda": [], "stress": stress})
                onset, stress = [], False
                continue
            onset.append(i)
            i += 1
        if onset and sylls:
            sylls[-1]["coda"] += onset
        return sylls

    def natural(self, text):
        """How Piper would say it unconstrained: per-syllable vowel onsets (seconds) and stress flags."""
        ids, syms, pred = self.tokens(text)
        sylls = self.syllables(syms)
        starts = np.concatenate([[0], np.cumsum(np.ceil(pred))[:-1]])
        return [starts[s["nucleus"][0]] / self.fps for s in sylls], [s["stress"] for s in sylls]

    def render(self, text, vowel_times, hold):
        """Synthesize `text` so syllable k's vowel starts at vowel_times[k] (seconds, relative to an
        arbitrary origin) and the last syllable holds for `hold` seconds.
        Returns (audio, start_time_of_audio_on_same_origin, syllables_with_sample_spans)."""
        ids, syms, pred = self.tokens(text)
        sylls = self.syllables(syms)
        if len(sylls) != len(vowel_times):
            raise ValueError(f"{len(sylls)} syllables but {len(vowel_times)} grid slots: {text!r}")

        def frames(idx_list, lo, hi):
            return sum(float(np.clip(pred[i] + pred[i + 1], lo, hi)) for i in idx_list)

        # target frame boundaries: vowel onsets on the grid, consonants borrowed from neighbours.
        # Consonants carry intelligibility, so they keep at least their natural length (3+ frames each).
        on = [frames(s["onset"], 3, 9) for s in sylls]
        co = [frames(s["coda"], 3, 8) for s in sylls]
        t0 = vowel_times[0] - on[0] / self.fps
        v = [(t - t0) * self.fps for t in vowel_times]
        end_nuc = []
        self.tight = []
        MIN_NUC = 4.0
        for k, s in enumerate(sylls):
            last = k + 1 == len(sylls)
            slot = (v[k] + hold * self.fps if last else v[k + 1]) - v[k]  # vowel-to-vowel frames
            nxt_on = 0.0 if last else on[k + 1]
            cons = co[k] + nxt_on
            if cons > slot - MIN_NUC and cons > 0:  # too tight: shrink consonants, but never below 70%
                f = max(0.7, max(0.0, slot - MIN_NUC) / cons)
                if f == 0.7:
                    self.tight.append(k)
                if co[k]:
                    co[k] = max(2.0, co[k] * f)
                if not last and on[k + 1]:
                    on[k + 1] = max(2.0, on[k + 1] * f)
                nxt_on = 0.0 if last else on[k + 1]
            end_nuc.append(max(2.0, slot - co[k] - nxt_on))

        # spread each group's frames over its tokens (symbol + following pad) by predicted share
        dur = np.zeros(len(ids))

        def spread(idx_list, total):
            if not idx_list:
                return
            weights = np.array([pred[i] + pred[i + 1] + 1e-3 for i in idx_list])
            for i, part in zip(idx_list, total * weights / weights.sum()):
                share = pred[i] / (pred[i] + pred[i + 1] + 1e-6)
                dur[i] += part * share
                dur[i + 1] += part * (1 - share)

        for k, s in enumerate(sylls):
            spread(s["onset"], on[k])
            spread(s["nucleus"], end_nuc[k])
            spread(s["coda"], co[k])

        # integer frames without drift: round the running sum
        cum = np.round(np.cumsum(dur))
        ints = np.diff(np.concatenate([[0], cum])).astype(np.float32)
        x = np.array([ids], dtype=np.int64)
        L = np.array([len(ids)], dtype=np.int64)
        audio = self.flow.run(None, {"input": x, "input_lengths": L, "scales": self.scales,
                                     "durations": ints.reshape(1, 1, -1), **self.extra})[0].squeeze()

        # sample spans of each syllable's vowel, for emphasis and for checking timing
        starts = np.concatenate([[0], cum[:-1]]) * HOP
        for s in sylls:
            s["vowel_sample"] = int(starts[s["nucleus"][0]])
            s["end_sample"] = int((cum[s["coda"][-1] + 1] if s["coda"] else cum[s["nucleus"][-1] + 1]) * HOP)
        return audio, t0, sylls
