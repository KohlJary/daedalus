#!/usr/bin/env python3
"""
measure_tokens.py: measure the input tokens of each encoding for the cost table (H5, amendment A6).

    python measure_tokens.py --tasks tasks/5016.jsonl --run pilot2-qwen3-8b --model qwen3:8b [--num-ctx 10240]
        [--variants ophanic@100,ophanic@60,prose,json,list,json-compact]

For every (structure, question) it sends one unframed, unfenced prompt per variant (the encoding, the question
and the instruction, as the pilot's prompt) and records only the model's own input count:
- each encoding in --variants, including `json-compact`: the same data as `json` with no whitespace
  (`separators=(",", ":")`), the primary comparator for H5;
- `bare`: the question and the instruction alone, so score.py subtracts the fixed part of each prompt and reports
  encoding-only counts. Framing is left out on purpose: it is a fixed cost per arm, not the encoding's.

Answers are not generated (num_predict 1). Rows go to results/<run>/tokens.jsonl, which score.py reads if present.
Resumable like run.py.

Backends: ollama (default; `prompt_eval_count`), or anthropic (`/v1/messages/count_tokens`, `input_tokens`),
which refuses to run unless OPX_ALLOW_PAID=1, like run.py's paid backend.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate import INSTRUCTION, prompt  # noqa: E402
from run import post  # noqa: E402


DEFAULT_VARIANTS = "ophanic@100,ophanic@60,prose,json,list,json-compact"


def variants(task, question, names=("json-compact",)):
    out = {}
    for v in names:
        if v == "json-compact" and v not in task["encodings"]:
            text = json.dumps(task["data"], separators=(",", ":"), ensure_ascii=False)
        else:
            text = task["encodings"][v]
        out[v] = prompt(text, question["text"])
    out["bare"] = f"{question['text']}\n{INSTRUCTION}"
    return out


def count_ollama(a, text):
    body = {"model": a.model, "messages": [{"role": "user", "content": text}], "stream": False,
            "think": False, "options": {"temperature": 0, "seed": 0, "num_ctx": a.num_ctx, "num_predict": 1}}
    return post(a.ollama_url.rstrip("/") + "/api/chat", body).get("prompt_eval_count")


def count_anthropic(a, text):
    body = {"model": a.model, "messages": [{"role": "user", "content": text}]}
    return post("https://api.anthropic.com/v1/messages/count_tokens", body,
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}).get("input_tokens")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--num-ctx", type=int, default=10240)
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--backend", choices=["ollama", "anthropic"], default="ollama")
    ap.add_argument("--variants", default=DEFAULT_VARIANTS)
    a = ap.parse_args(argv)
    if a.backend == "anthropic" and os.environ.get("OPX_ALLOW_PAID") != "1":
        sys.exit("refusing: the anthropic backend needs OPX_ALLOW_PAID=1, set only when Kohl has started paid runs")
    names = [v for v in a.variants.split(",") if v]
    count = count_ollama if a.backend == "ollama" else count_anthropic

    tasks = [json.loads(x) for x in Path(a.tasks).read_text(encoding="utf-8").splitlines() if x.strip()]
    out_path = HERE / "results" / a.run / "tokens.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
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
                for v, text in variants(t, q, names).items():
                    if (t["id"], q["id"], v, a.model) in done:
                        continue
                    row = {"task": t["id"], "type": t["type"], "size": t["size"], "question_id": q["id"],
                           "variant": v, "model": a.model, "backend": a.backend, "num_ctx": a.num_ctx,
                           "prompt_chars": len(text)}
                    try:
                        row["prompt_eval_count"] = count(a, text)
                    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as ex:
                        row["error"] = f"{type(ex).__name__}: {ex}"
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n += 1
    print(f"{n} prompts measured; wrote {out_path}")


if __name__ == "__main__":
    main()
