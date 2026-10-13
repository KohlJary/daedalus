"""Feasibility spike: can a local Ollama model act as an Ariadne worker via a 4-tool loop?

Throwaway. Mirrors proposal #16: list_files, read_file, write_file (whole file), run_tests,
over the OpenAI-compatible endpoint. Runs against the hermetic tier's fixture project.
Usage: python spike_local_worker.py MODEL TASK   (TASK: add_sub | fix_bug)
"""
import json, subprocess, sys, tempfile, time
from pathlib import Path
import os
import httpx
TEMP = float(os.environ.get("TEMP", "0"))

BASE = "http://localhost:11434/v1"
CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
TEST_CALC = ("from calc import add, mul\n\n\n"
             "def test_add():\n    assert add(2, 3) == 5\n\n\n"
             "def test_mul():\n    assert mul(2, 3) == 6\n")
TASKS = {
    "add_sub": ("Add a function sub(a, b) to calc.py that returns a - b, and add a test test_sub "
                "for it in tests/test_calc.py. Keep the existing functions and tests."),
    "fix_bug": "The tests are failing. Find and fix the bug in calc.py. Do not change the tests.",
    "new_module": ("Create a new module stats.py with a function mean(xs) that returns the arithmetic mean "
                   "of a list of numbers and raises ValueError if the list is empty. Add tests in "
                   "tests/test_stats.py covering a normal list and the empty case. Do not modify calc.py."),
}
TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List files in the project.",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's full contents.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file",
     "description": "Overwrite a file with the complete new contents (whole file, not a patch).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_tests", "description": "Run the project's pytest suite.",
     "parameters": {"type": "object", "properties": {}}}},
]
SYSTEM = ("You are a coding worker. Use the tools to complete the task in the project. Read files before "
          "changing them. write_file replaces the whole file. Run the tests when done. When the task is "
          "complete and tests pass, reply with a one-line summary and no tool call.")


def make_project(task: str) -> Path:
    repo = Path(tempfile.mkdtemp(prefix="spike-")) / "project"
    (repo / "tests").mkdir(parents=True)
    calc = CALC.replace("return a * b", "return a + b") if task == "fix_bug" else CALC
    (repo / "calc.py").write_text(calc)
    (repo / "tests" / "test_calc.py").write_text(TEST_CALC)
    (repo / "conftest.py").write_text("")
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", *c], cwd=repo, check=True)
    return repo


def run_tool(repo: Path, name: str, args: dict) -> str:
    def safe(p):
        target = (repo / p).resolve()
        if not str(target).startswith(str(repo.resolve())):
            raise ValueError("path outside project")
        return target
    if name == "list_files":
        return "\n".join(str(p.relative_to(repo)) for p in sorted(repo.rglob("*"))
                         if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts)
    if name == "read_file":
        return safe(args["path"]).read_text()
    if name == "write_file":
        t = safe(args["path"]); t.parent.mkdir(parents=True, exist_ok=True); t.write_text(args["content"])
        return f"wrote {args['path']} ({len(args['content'])} chars)"
    if name == "run_tests":
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=repo,
                           capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr)[-2000:]
    return f"unknown tool {name}"


def main(model: str, task: str, max_steps: int = 12):
    repo = make_project(task)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": TASKS[task]}]
    t0, calls, bad, step = time.time(), 0, 0, 0
    for step in range(max_steps):
        r = httpx.post(f"{BASE}/chat/completions", timeout=600,
                       json={"model": model, "messages": msgs, "tools": TOOLS, "temperature": TEMP})
        msg = r.json()["choices"][0]["message"]
        msgs.append(msg)
        tcs = msg.get("tool_calls") or []
        if not tcs:
            print(f"  [final] {(msg.get('content') or '')[:200]!r}")
            break
        for tc in tcs:
            calls += 1
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                out = run_tool(repo, name, args)
            except Exception as e:
                bad += 1; out = f"error: {e}"
            print(f"  [{step}] {name}({', '.join(args) if isinstance(args, dict) else ''}) -> {out.splitlines()[-1][:90] if out.strip() else ''}")
            msgs.append({"role": "tool", "tool_call_id": tc.get("id", name), "content": out})
    final = run_tool(repo, "run_tests", {})
    diff = subprocess.run(["git", "diff", "--stat"], cwd=repo, capture_output=True, text=True).stdout
    tests_touched = "test_calc.py" in diff
    calc_touched = "calc.py" in diff.replace("test_calc.py", "")
    if task == "new_module":
        extra = subprocess.run([sys.executable, "-c", "import stats\ntry:\n stats.mean([])\n print('no-raise')\nexcept ValueError:\n print('ok' if stats.mean([1,2,3,6])==3 else 'wrong')"],
                               cwd=repo, capture_output=True, text=True).stdout.strip() or "import-fail"
    else:
        extra = "-"
    passed = " passed" in final and "failed" not in final and "error" not in final.lower()
    n_tests = final.split(" passed")[0].split()[-1] if " passed" in final else "0"
    print(f"RESULT model={model} task={task} pass={passed} tests_passed={n_tests} "
          f"tests_touched={tests_touched} calc_touched={calc_touched} check={extra} steps={step+1} tool_calls={calls} bad_calls={bad} "
          f"secs={time.time()-t0:.0f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
