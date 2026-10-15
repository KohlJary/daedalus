#!/usr/bin/env python3
"""
run.py: send each (structure, encoding, question) to a model and record one JSON line per call.

    python run.py --tasks tasks/1015.jsonl --run pilot-qwen3-8b --model qwen3:8b \
        [--encodings ophanic@100,ophanic@60,prose,json,list] [--noise-every 2] [--limit N] [--dry-run]

Every prompt is the encoding, a blank line, the question, and the same instruction: "Answer with only the
answer." Calls go out at temperature 0. Results go to results/<run>/calls.jsonl; a rerun skips calls already
recorded without an error, so runs are resumable.

Backends:
- ollama (default): the native /api/chat at --ollama-url, with `think: false` and `options.num_ctx` fixed for
  the whole run (big enough for the largest prompt), so the model is loaded once.
- anthropic: the Messages API. It refuses to run unless OPX_ALLOW_PAID=1 is set: paid runs start only when
  Kohl starts them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate import prompt  # noqa: E402
from score import correct  # noqa: E402

DEFAULT_ENCODINGS = "ophanic@100,ophanic@60,prose,json,list"


def post(url, body, headers=None, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def call_ollama(a, text):
    body = {"model": a.model, "messages": [{"role": "user", "content": text}], "stream": False, "think": False,
            "options": {"temperature": 0, "seed": 0, "num_ctx": a.num_ctx, "num_predict": a.max_tokens}}
    r = post(a.ollama_url.rstrip("/") + "/api/chat", body)
    return {"answer": r.get("message", {}).get("content", ""), "prompt_eval_count": r.get("prompt_eval_count"),
            "eval_count": r.get("eval_count"), "thinking": bool(r.get("message", {}).get("thinking"))}


def call_anthropic(a, text):
    body = {"model": a.model, "max_tokens": a.max_tokens, "temperature": 0,
            "messages": [{"role": "user", "content": text}]}
    r = post("https://api.anthropic.com/v1/messages", body,
             {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    answer = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    u = r.get("usage", {})
    return {"answer": answer, "prompt_eval_count": u.get("input_tokens"), "eval_count": u.get("output_tokens"),
            "model_id": r.get("model")}


def plan(tasks, encodings, noise_every):
    for t in tasks:
        encs = list(encodings)
        if noise_every and t["index"] % noise_every == 0:
            encs.append("ophanic-noise@100")
        for e in encs:
            for qq in t["questions"]:
                yield t, e, qq


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--run", required=True, help="name of the results/<run> directory")
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", choices=["ollama", "anthropic"], default="ollama")
    ap.add_argument("--encodings", default=DEFAULT_ENCODINGS)
    ap.add_argument("--noise-every", type=int, default=2,
                    help="add ophanic-noise@100 for structures whose index is a multiple of this (0: none)")
    ap.add_argument("--num-ctx", type=int, default=0, help="0: the next 2048 above the largest prompt's estimate")
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many new calls (0: all)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the num_ctx, call nothing")
    a = ap.parse_args(argv)

    if a.backend == "anthropic":
        if os.environ.get("OPX_ALLOW_PAID") != "1":
            sys.exit("refusing: the anthropic backend is a paid run; set OPX_ALLOW_PAID=1 only when Kohl has "
                     "started paid runs (none before 2026-10-23)")
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY is not set")

    tasks_path = Path(a.tasks)
    tasks = [json.loads(x) for x in tasks_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    encodings = [e for e in a.encodings.split(",") if e]
    calls = list(plan(tasks, encodings, a.noise_every))
    prompts = [prompt(t["encodings"][e], qq["text"]) for t, e, qq in calls]
    if not a.num_ctx:
        # A box-drawing character can cost a token on its own: estimate one token per character, with room
        # for the chat template and the answer
        biggest = max(len(p) for p in prompts)
        a.num_ctx = ((biggest + 256 + a.max_tokens) // 2048 + 1) * 2048
    run_dir = HERE / "results" / a.run
    out_path = run_dir / "calls.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add((r["task"], r["encoding"], r["question_id"], r["model"]))
    todo = [(c, p) for c, p in zip(calls, prompts) if (c[0]["id"], c[1], c[2]["id"], a.model) not in done]
    print(f"{len(calls)} calls planned, {len(calls) - len(todo)} already done, {len(todo)} to go; "
          f"num_ctx={a.num_ctx}; largest prompt {max(len(p) for p in prompts)} chars")
    if a.dry_run:
        return
    run_dir.mkdir(parents=True, exist_ok=True)
    fn = call_ollama if a.backend == "ollama" else call_anthropic
    started = time.time()
    with out_path.open("a", encoding="utf-8") as f:
        for n, ((t, e, qq), text) in enumerate(todo, 1):
            if a.limit and n > a.limit:
                break
            t0 = time.time()
            row = {"run": a.run, "tasks_file": tasks_path.name, "task": t["id"], "type": t["type"], "size": t["size"],
                   "elements": t["elements"], "encoding": e, "question_id": qq["id"], "kind": qq["kind"],
                   "sub": qq["sub"], "question": qq["text"], "answer_type": qq["answer_type"], "gold": qq["gold"],
                   "model": a.model, "backend": a.backend, "num_ctx": a.num_ctx if a.backend == "ollama" else None,
                   "prompt_chars": len(text)}
            try:
                row.update(fn(a, text))
                row["correct"] = correct(qq, row["answer"])
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as ex:
                row.update({"answer": "", "error": f"{type(ex).__name__}: {ex}"})
            row["latency_s"] = round(time.time() - t0, 3)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if n % 50 == 0 or row.get("error"):
                rate = (time.time() - started) / n
                print(f"  {n}/{len(todo)}  {rate:.2f}s/call  eta {rate * (len(todo) - n) / 60:.1f} min"
                      + (f"  ERROR {row['error']}" if row.get("error") else ""), flush=True)


if __name__ == "__main__":
    main()
