#!/usr/bin/env python3
"""
run.py: send each (structure, encoding, question) to a model and record one JSON line per call.

    python run.py --tasks tasks/5016.jsonl --run pilot2-qwen3-8b --model qwen3:8b \
        [--encodings ophanic@100,ophanic@60,prose,json,list] [--noise-every 1] [--framing on] [--fenced]
        [--max-tokens 256] [--stop STOP] [--think] [--limit N] [--dry-run]

Every prompt is a one-sentence framing for the arm (A3), the encoding, a blank line, the question, and the same
instruction: "Answer with only the answer." `--framing off` gives the pilot's unframed prompt. An arm may carry
modifiers: `ophanic@100+fenced` wraps the diagram in a ``` fence, `prose+unframed` drops that arm's framing, so a
run can compare variants on the same structures. `--fenced` adds `+fenced` to every ophanic arm.

Calls go out at temperature 0 (Ollama) with a stop sequence (default a blank line, so a looping list ends) and
num_predict large enough for any short answer (A2). Each row records the API's done/stop reason, so answers cut
off by the token limit are counted. Results go to results/<run>/calls.jsonl; a rerun skips calls already recorded
without an error, so runs are resumable.

Backends (A8: the model is --model):
- ollama (default): the native /api/chat at --ollama-url, with `think: false` (or `--think`) and `options.num_ctx`
  fixed for the whole run (big enough for the largest prompt), so the model is loaded once. qwen3:8b was the
  pilots' model; qwen3:14b is the proposed confirmatory local model.
- anthropic: the Messages API, with --model a Claude model ID. It refuses to run unless OPX_ALLOW_PAID=1 is set:
  paid runs start only when Kohl starts them. Temperature is sent only if --temperature is given (current
  models reject it); `--effort` sets output_config.effort.
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
from generate import build_prompt, parse_arm  # noqa: E402
from score import correct  # noqa: E402

DEFAULT_ENCODINGS = "ophanic@100,ophanic@60,prose,json,list"


def post(url, body, headers=None, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_body(a, text):
    options = {"temperature": 0 if a.temperature is None else a.temperature, "seed": 0, "num_ctx": a.num_ctx,
               "num_predict": a.max_tokens}
    if a.stop:
        options["stop"] = [a.stop]
    return {"model": a.model, "messages": [{"role": "user", "content": text}], "stream": False, "think": a.think,
            "options": options}


def call_ollama(a, text):
    r = post(a.ollama_url.rstrip("/") + "/api/chat", ollama_body(a, text))
    return {"answer": r.get("message", {}).get("content", ""), "prompt_eval_count": r.get("prompt_eval_count"),
            "eval_count": r.get("eval_count"), "thinking": bool(r.get("message", {}).get("thinking")),
            "done_reason": r.get("done_reason")}


def anthropic_body(a, text):
    body = {"model": a.model, "max_tokens": a.max_tokens, "messages": [{"role": "user", "content": text}]}
    if a.temperature is not None:
        body["temperature"] = a.temperature
    if a.stop and a.stop.strip():   # a whitespace-only stop sequence is not sent to the Messages API
        body["stop_sequences"] = [a.stop]
    if a.effort:
        body["output_config"] = {"effort": a.effort}
    return body


def call_anthropic(a, text):
    r = post("https://api.anthropic.com/v1/messages", anthropic_body(a, text),
             {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
    answer = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    if a.stop and not a.stop.strip() and a.stop in answer:
        answer = answer.split(a.stop)[0]   # the stop applied client-side, as Ollama would have
    u = r.get("usage", {})
    return {"answer": answer, "prompt_eval_count": u.get("input_tokens"), "eval_count": u.get("output_tokens"),
            "model_id": r.get("model"), "done_reason": r.get("stop_reason")}


def noise_arm(encodings):
    """The noise arm pairs with the first ophanic@100 arm, with the same modifiers."""
    for e in encodings:
        base, mods = parse_arm(e)
        if base == "ophanic@100":
            return "+".join(["ophanic-noise@100", *sorted(mods)])
    return "ophanic-noise@100"


def plan(tasks, encodings, noise_every):
    for t in tasks:
        encs = list(encodings)
        if noise_every and t["index"] % noise_every == 0:
            encs.append(noise_arm(encodings))
        for e in encs:
            for qq in t["questions"]:
                yield t, e, qq


def arms(spec, fenced):
    out = [e for e in spec.split(",") if e]
    if fenced:
        out = [e + "+fenced" if parse_arm(e)[0].startswith("ophanic") and "fenced" not in parse_arm(e)[1] else e
               for e in out]
    for e in out:
        parse_arm(e)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--run", required=True, help="name of the results/<run> directory")
    ap.add_argument("--model", required=True)
    ap.add_argument("--backend", choices=["ollama", "anthropic"], default="ollama")
    ap.add_argument("--encodings", default=DEFAULT_ENCODINGS)
    ap.add_argument("--noise-every", type=int, default=1,
                    help="add ophanic-noise@100 for structures whose index is a multiple of this (1: all, the A5 "
                         "default; 2: every other, as the pilot ran; 0: none)")
    ap.add_argument("--framing", choices=["on", "off"], default="on",
                    help="A3: a neutral sentence per arm saying what the structure is and how to read it")
    ap.add_argument("--fenced", action="store_true", help="wrap every ophanic arm in a ``` fence (+fenced)")
    ap.add_argument("--num-ctx", type=int, default=0, help="0: the next 2048 above the largest prompt's estimate")
    ap.add_argument("--max-tokens", type=int, default=256,
                    help="num_predict / max_tokens: room for any short answer (raise it with --think)")
    ap.add_argument("--stop", default="\n\n", help="stop sequence (default: a blank line); '' for none")
    ap.add_argument("--think", action="store_true", help="ollama: let a reasoning model think (default off)")
    ap.add_argument("--temperature", type=float, default=None,
                    help="ollama default 0; anthropic: sent only if given")
    ap.add_argument("--effort", default=None, help="anthropic: output_config.effort (low, medium, high...)")
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
    a.stop = a.stop.encode().decode("unicode_escape") if "\\" in a.stop else a.stop
    encodings = arms(a.encodings, a.fenced)
    calls = list(plan(tasks, encodings, a.noise_every))
    framing = a.framing == "on"
    prompts = [build_prompt(t, e, qq["text"], framing) for t, e, qq in calls]
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
                   "prompt_chars": len(text), "harness": t.get("harness", 1), "framing": framing,
                   "max_tokens": a.max_tokens, "stop": a.stop, "think": a.think}
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
