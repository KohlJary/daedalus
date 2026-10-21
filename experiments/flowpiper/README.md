# flowpiper: rap engine experiment

Parked here so it isn't lost. It's an experiment, not part of the plugin: nothing in this folder ships with
`daedalus hydrate`. The idea is that hit-em-up's closing verse could one day be performed over a beat.

**Status:** the duration override, beat synthesis, score playback and MCFlow-borrowed timing are built and
working. The words are legible-ish, and the delivery is still read-aloud Piper prosody. Write-to-flow
templates, per-MC beats and abstract flow styles are ideas, not built yet.

`demos/` holds the latest render, a 16-bar battle (Hotfix vs Coverage) with its transcript. The transcript
lists which real verse each bar's timing came from.

## How it works

- **Rhythm (`flowpiper_build.py`, `flowpiper.py`).** Piper voices are VITS models, which predict how many
  frames each phoneme lasts (the `w_ceil` node in the ONNX graph) before generating audio. The build script
  makes two copies of a voice: `*.predict.onnx` also outputs those predicted durations, and `*.flow.onnx`
  takes durations as an input instead. `flowpiper.py` splits each phrase into syllables, keeps consonants
  near their natural length (they carry intelligibility), puts every vowel on its target time, and stretches
  vowels to fill the gaps. One frame is 256 samples, so placement is exact to about 6 ms.
- **Beat (`beat.py`, `grid.py`).** Synthesized from scratch with numpy: 94 BPM, 62% swing, a Moog-style
  bass through a resonant ladder filter, a kit with ghost notes, dark keys and a portamento lead. No samples.
- **Scores (`play.py`, `verse.flow`).** A hand-written score: `<bar>.<step> <rhythm> | <words>`, one
  character per sixteenth (`X` accented, `x` syllable, `-` hold). The player drags 30 ms behind the beat
  with a little human looseness, shapes pitch with the WORLD vocoder, and writes a transcript.
- **Real flow (`battle.py`, `mcflow.py`, `battle.flow`).** Timing borrowed from MCFlow, Condit-Schultz's
  corpus of transcribed rap verses (3,422 usable bars). For each lyric bar it finds real bars with the same
  syllable count and the closest stress pattern, preferring a rhyme where ours falls and a gap where our
  phrases break. Each MC takes all its bars from one rapper, the best overall fit, for a coherent flow. The
  vocal chain is a light "cupped battle mic" (honk around 1.3 kHz, thinned lows, compression) plus a short
  plate reverb.
- **Older auto-flow (`song.py`, `quantize.py`, `verse.txt`).** One syllable per sixteenth, or Piper's
  natural rhythm quantized to the grid. Kept for comparison; it sounds square.
- **Helpers.** `audition.py` ranks multi-speaker voices by pitch; `bands.py` prints a mix's energy by band.

## Setup

```
pip install piper-tts onnx onnxruntime numpy scipy soundfile pyworld
mkdir voices
# voices from Piper's GitHub release v0.0.2 (Hugging Face hosts the newer ones):
curl -L https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-ryan-high.tar.gz | tar xz -C voices
curl -L https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en-us-libritts-high.tar.gz | tar xz -C voices
python flowpiper_build.py voices/en-us-ryan-high.onnx
python flowpiper_build.py voices/en-us-libritts-high.onnx
git clone https://github.com/Computational-Cognitive-Musicology-Lab/MCFlow
```

Paths can be overridden with `FLOWPIPER_VOICE`, `FLOWPIPER_MULTI_VOICE` and `MCFLOW_DIR`.

## Run

```
python beat.py                  # beat.wav (grid.py sets tempo, swing and bar count)
python battle.py battle.flow    # battle_mcflow.wav + battle_mcflow_transcript.md
python play.py verse.flow       # single-MC score playback
```

Set `N_BARS` in `grid.py` to cover the score before rendering the beat. In a score, `@ <voice.onnx>
<speaker> <pan> <pitch shift>` switches voices; `battle.py` uses only the bars, voices and words, not the
rhythm strings.

## What we learned

- Equal sixteenths sound like an 80s novelty rap. Flow is composition: the rhythm has to be written (or
  borrowed), not computed from the words.
- Writing matters as much as timing. Bars need imagery and wordplay, and two MCs with opposed positions
  wrote far better bars than one MC narrating.
- Per-bar matching repeats itself: one MC got the same 50 Cent bar shape six times. Real verses vary bar to
  bar, and rhymes move inside the bar, not just at the end (Adams, "On the Metrical Techniques of Flow in Rap
  Music," Music Theory Online 15.5).
- Piper's voices carry read-aloud prosody, and some LibriTTS speakers are noisy in the model itself.
  Attitude needs training on aggressive delivery or a style-controllable voice model.

## Next

1. **Write-to-flow templates.** Take a run of consecutive bars from one real verse (its natural variation,
   enjambment and moving rhyme slots) and hand the bar writer a template: syllables per bar, stressed slots,
   and which slots rhyme with which. Real rappers often find the flow first, then write to it. This is the
   contract for the clash protocol's MCs.
2. **Per-MC beats**, chosen from each MC's flow source (tempo and feel), with a DJ-style cut at the handoff.
3. **Abstract flow styles** defined by their patterns (syllable rate, triplets, syncopation, rhyme
   placement), with artist templates as one way to fill them. MCFlow is Billboard rap from 1979 to 2014, so
   chopper, horrorcore and drill styles would need hand-seeded templates.
4. **Pitch and attitude**: a vocoder emphasis pass, and eventually fine-tuning on recorded rap delivery
   from a consenting voice.
5. **A flow that plays with the beat.** The flow and the beat don't interact yet: `battle.py` picks MCFlow bars
   by our lyrics' syllables and stress, then lays them on a generic grid. The beat is ours, so every onset is
   already known from `grid.py` (no audio analysis needed). Ideas:
   - **Beat-aware bar choice:** add an alignment term to the MCFlow lookup. Reward stressed syllables on or just
     ahead of the snare and rhymes on accents. Reward phrase breaks where the kit fills or the bass drops out.
     Penalize crowding the lead's phrases.
   - **Pocket against the kick:** reward syllables in the gaps between kicks, not doubling them; stresses with the snare.
   - **Sections drive the shape:** mark intro, drop and breakdown in the beat. The flow answers: sparse on the
     intro, double-time where the hats roll, a held vowel or a rest on the drop.
   - **Pitch from the bass:** pull each bar's WORLD pitch contour toward the bass root and key, so the voice sits
     in the track.
   - **Call and response:** leave holes for the lead to answer; ad-libs on the beat's signature hits.
