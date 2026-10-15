# flowpiper: Piper on the beat

Makes a Piper voice rap on a grid by overriding the phoneme durations inside the VITS model.
Every syllable's vowel lands within half a frame (about 6 ms) of its target sixteenth.

## How it works

Piper voices are VITS models. Before generating audio, VITS predicts how many frames each phoneme
lasts (the `w_ceil` node in the ONNX graph). `flowpiper_build.py` makes two copies of a voice:

- `*.predict.onnx` also outputs those predicted durations, so we know how long consonants naturally are;
- `*.flow.onnx` replaces the prediction with a `durations` input, so we decide.

`flowpiper.py` splits each line into syllables (onset consonants, vowel, coda), keeps consonants
near their natural length, puts each vowel on its grid time, and stretches the vowels to fill the
gaps. One duration frame is 256 samples, so placement is exact up to rounding.

## Run it

```
pip install piper-tts onnx onnxruntime numpy soundfile
python flowpiper_build.py path/to/voice.onnx      # once per voice; voice.onnx.json must sit beside it
python beat.py                                    # synthesizes beat.wav (94 BPM, F minor, 62% swing, Moog-style bass)
python play.py                                    # plays the score verse.flow -> hit_em_up_v3.wav + transcript.md
python song.py quantized                          # older auto-flow over verse.txt (or: straight)
```

Change the voice path near the top of `play.py`. `verse.flow` is the score: each line is one phrase,
`<bar>.<step> <rhythm> | <words>`, where the rhythm has one character per sixteenth (`X` accented
syllable, `x` syllable, `-` hold). The player drags 30 ms behind the beat with a little human looseness,
lifts pitch on accents and lets each phrase fall at the end (WORLD vocoder), and writes a transcript.

For the older auto-flow, change the voice path at the top of `song.py`. Edit `verse.txt` (one line per bar, 15 syllables max;
the last syllable of each line lands on beat 4).

## Battles with real flow (MCFlow)

`battle.py battle.flow` renders a two-MC battle. For each bar it finds bars in the MCFlow corpus
(Condit-Schultz; github.com/Computational-Cognitive-Musicology-Lab/MCFlow) with the same syllable count
and the closest stress pattern, preferring a rhyme where ours falls and a gap where our phrases break, and
inherits their timing, triplets and rests included. Clone MCFlow and point `battle.py` at its `Humdrum`
folder. Voices are switched in the score with `@ <voice.onnx> <speaker> <pan> <pitch shift>`.

## Limits

- Rhythm only. VITS has no pitch control, so the delivery is deadpan; stressed syllables and rhymes
  get a volume lift, not a pitch lift.
- Syllable splitting is a simple vowel-run rule; diphthongs count as one syllable, and two vowels in
  a row inside a word may merge.
- Two flow modes: `straight` gives every syllable one sixteenth; `quantized` (default) starts from
  Piper's natural rhythm, stretches the line so the rhyme lands on beat 4, and snaps each syllable to
  the grid, pulling stressed syllables onto beats and eighths (`quantize.py`).
- Next steps: pitch emphasis with a vocoder pass (WORLD), flow templates beyond straight sixteenths
  (triplets, rests mid-line), and fine-tuning on recorded rap delivery.
