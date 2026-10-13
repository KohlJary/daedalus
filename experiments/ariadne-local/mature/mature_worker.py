"""Worker tool loop for a real-sized codebase: ranged reads, search, and exact-match edits instead of
whole-file writes (an 8B model rewriting a 700-line file to change 3 lines is how files get clobbered).
Every condition, including the single-agent baseline, gets these same tools."""
import json, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gate_exp"))
import exp  # noqa: E402  (chat() and token accounting)

MAX_READ_LINES = 250
PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"]

TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List files under a directory (default: whole project).",
     "parameters": {"type": "object", "properties": {"dir": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "search", "description": "Search the project for a regex (like grep -rn). Returns up to 60 matching lines as path:line:text.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "dir": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "read_file", "description": f"Read lines of a file, numbered. At most {MAX_READ_LINES} lines per call; use start_line to page.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Replace an exact snippet in a file. old_text must appear exactly once (include enough surrounding lines to make it unique); it is replaced by new_text.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {"name": "create_file", "description": "Create a NEW file with the given content. Fails if the file exists; use edit_file to change existing files.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_tests", "description": "Run pytest (optionally one test file or test id). Stops at the first failure.",
     "parameters": {"type": "object", "properties": {"target": {"type": "string"}}}}},
]

SYSTEM = ("You are a coding worker on a large existing codebase. Use the tools to complete the task. Find the "
          "relevant code with search, read only the parts you need, and change existing files with edit_file "
          "(exact snippets; never rewrite whole files). Follow the codebase's existing style. Run the relevant "
          "tests when done. When the task is complete, reply with a one-line summary and no tool call.")

SKIP = {".git", "__pycache__", ".pytest_cache"}


def _safe(repo: Path, p: str) -> Path:
    t = (repo / (p or ".")).resolve()
    if not str(t).startswith(str(repo.resolve())):
        raise ValueError("path outside project")
    return t


def run_tool(repo: Path, name: str, args: dict) -> str:
    if name == "list_files":
        root = _safe(repo, args.get("dir", ""))
        files = [str(p.relative_to(repo)) for p in sorted(root.rglob("*")) if p.is_file() and not SKIP & set(p.parts)]
        return "\n".join(files[:400]) + (f"\n... ({len(files) - 400} more)" if len(files) > 400 else "")
    if name == "search":
        root = _safe(repo, args.get("dir", ""))
        r = subprocess.run(["grep", "-rnE", "--exclude-dir=.git", "--exclude-dir=__pycache__", "-I", args["pattern"], str(root)],
                           capture_output=True, text=True, timeout=30)
        lines = [l.replace(str(repo) + "/", "", 1)[:220] for l in r.stdout.splitlines()]
        return "\n".join(lines[:60]) + (f"\n... ({len(lines) - 60} more matches)" if len(lines) > 60 else "") or "no matches"
    if name == "read_file":
        lines = _safe(repo, args["path"]).read_text().splitlines()
        start = max(int(args.get("start_line") or 1), 1)
        end = min(int(args.get("end_line") or start + MAX_READ_LINES - 1), start + MAX_READ_LINES - 1, len(lines))
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        more = f"\n[lines {start}-{end} of {len(lines)}; read further with start_line={end + 1}]" if end < len(lines) else f"\n[end of file, {len(lines)} lines]"
        return body + more
    if name == "edit_file":
        f = _safe(repo, args["path"])
        s = f.read_text()
        n = s.count(args["old_text"])
        if n != 1:
            return f"error: old_text found {n} times in {args['path']} (must be exactly once); read the file and use an exact, unique snippet"
        f.write_text(s.replace(args["old_text"], args["new_text"]))
        return f"edited {args['path']}"
    if name == "create_file":
        f = _safe(repo, args["path"])
        if f.exists():
            return f"error: {args['path']} exists; use edit_file"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(args["content"])
        return f"created {args['path']}"
    if name == "run_tests":
        cmd = PYTEST + ([args["target"]] if args.get("target") else [])
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=300)
        return (r.stdout + r.stderr)[-3500:]
    return f"unknown tool {name}"


def work_mature(model: str, repo: Path, prompt: str, max_steps: int = 30) -> dict:
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    t0, calls, bad, steps, final, err = time.time(), 0, 0, 0, "", None
    tool_names = []
    try:
        for steps in range(1, max_steps + 1):
            msg = exp.chat(model, msgs, TOOLS)
            msgs.append({k: msg[k] for k in ("role", "content", "tool_calls") if k in msg})
            tcs = msg.get("tool_calls") or []
            if not tcs:
                final = msg.get("content") or ""
                break
            for tc in tcs:
                calls += 1
                name = tc["function"]["name"]
                tool_names.append(name)
                args = tc["function"].get("arguments") or {}
                try:
                    if isinstance(args, str):
                        args = json.loads(args)
                    out = run_tool(repo, name, args)
                    if out.startswith("error:"):
                        bad += 1
                except Exception as e:
                    bad += 1
                    out = f"error: {e}"
                msgs.append({"role": "tool", "content": out, "tool_name": name})
        else:
            err = "max_steps"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    return dict(steps=steps, tool_calls=calls, bad_calls=bad, final=final[:500], worker_error=err,
                worker_secs=round(time.time() - t0, 1), tools_used=tool_names)
