#!/usr/bin/env python3
"""
measure_tokens.py: measure prompt token counts that the accuracy run didn't record (Momus, pilot review).

    python measure_tokens.py --tasks tasks/1015.jsonl --run pilot-qwen3-8b --model qwen3:8b [--num-ctx 10240]

For every (structure, question) it sends two extra prompts to the model and records only `prompt_eval_count`:
- `json-compact`: the same data as the `json` encoding, without indentation (`separators=(",", ":")`);
- `bare`: the question and the instruction alone, with no encoding, so score.py can subtract the fixed part of
  each prompt and report encoding-only token counts.

Answers are not scored (num_predict 1). Rows go to results/<run>/tokens.jsonl, which score.py reads if present.
Resumable like run.py. Local only: it has no paid backend.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate import INSTRUCTION, prompt  # noqa: E402
from run import post  # noqa: E402


def variants(task, question):
    compact = json.dumps(task["data"], separators=(",", ":"), ensure_ascii=False)
    return {"json-compact": prompt(compact, question["text"]),
            "bare": f"{question['text']}\n{INSTRUCTION}"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--num-ctx", type=int, default=10240)
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    a = ap.parse_args(argv)

    tasks = [json.loads(x) for x in Path(a.tasks).read_text(encoding="utf-8").splitlines() if x.strip()]
    out_path = HERE / "results" / a.run / "tokens.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("prompt_eval_count"):
                done.add((r["task"], r["question_id"], r["variant"], r["model"]))
    n = 0
    with out_path.open("a", encoding="utf-8") as f:
        for t in tasks:
            for q in t["questions"]:
                for v, text in variants(t, q).items():
                    if (t["id"], q["id"], v, a.model) in done:
                        continue
                    body = {"model": a.model, "messages": [{"role": "user", "content": text}], "stream": False,
                            "think": False, "options": {"temperature": 0, "seed": 0, "num_ctx": a.num_ctx,
                                                         "num_predict": 1}}
                    row = {"task": t["id"], "type": t["type"], "size": t["size"], "question_id": q["id"],
                           "variant": v, "model": a.model, "num_ctx": a.num_ctx, "prompt_chars": len(text)}
                    try:
                        row["prompt_eval_count"] = post(a.ollama_url.rstrip("/") + "/api/chat", body).get(
                            "prompt_eval_count")
                    except (urllib.error.URLError, TimeoutError, ValueError) as ex:
                        row["error"] = f"{type(ex).__name__}: {ex}"
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n += 1
    print(f"{n} prompts measured; wrote {out_path}")


if __name__ == "__main__":
    main()
