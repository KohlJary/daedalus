"""Load MCFlow (Condit-Schultz) bars as rhythm templates.

Each bar becomes a list of syllables with position in the bar (beats from the downbeat), duration
(beats), stress (0/1) and whether it carries a rhyme. Only rhythm, stress and rhyme are kept; the
lyrics are not used.
"""
import glob
import re


def recip_beats(tok):
    tok = tok.strip()
    m = re.fullmatch(r"(\d+)(?:%(\d+))?(\.*)", tok)
    if not m:
        return None
    den, num, dots = int(m.group(1)), int(m.group(2) or 1), len(m.group(3))
    if den == 0:
        return None
    base = 4.0 * num / den
    return base * (2 - 0.5 ** dots)


def load_bars(folder, tempo_range=(80, 106)):
    bars = []
    for path in sorted(glob.glob(f"{folder}/*.rap")):
        tempo, cols, cur, pos, song, mc = None, None, [], 0.0, path.rsplit("/", 1)[-1], None
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.rstrip("\n")
            if line.startswith("**"):
                cols = line.split("\t")
                continue
            if line.startswith("!MC:"):
                mc = line.split("\t")[0][4:].strip()
                continue
            if cols is None or line.startswith("!"):
                continue
            f = line.split("\t")
            if line.startswith("*"):
                mm = re.match(r"\*MM([\d.]+)", f[0])
                if mm:
                    tempo = float(mm.group(1))
                continue
            if line.startswith("="):
                if cur and tempo and tempo_range[0] <= tempo <= tempo_range[1] and abs(pos - 4.0) < 0.05:
                    bars.append({"song": song, "mc": mc or song.split("_")[0], "tempo": tempo, "syl": cur})
                cur, pos = [], 0.0
                continue
            if len(f) < len(cols):
                continue
            row = dict(zip(cols, f))
            dur = recip_beats(row.get("**recip", "."))
            if dur is None:
                continue
            stress = row.get("**stress", ".")
            if stress in ("0", "1"):
                rhyme = row.get("**rhyme", ".").strip("()")
                cur.append({"pos": pos, "dur": dur, "stress": int(stress),
                            "rhyme": rhyme not in (".", ""), "brk": row.get("**break", ".")})
            pos += dur
    return bars


if __name__ == "__main__":
    import collections
    import os
    bars = load_bars(os.environ.get("MCFLOW_DIR", "MCFlow/Humdrum"))
    counts = collections.Counter(len(b["syl"]) for b in bars)
    print(len(bars), "complete 4/4 bars between 80 and 106 BPM")
    print("syllables per bar:", sorted(counts.items()))
