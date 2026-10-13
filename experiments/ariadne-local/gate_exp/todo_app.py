"""A small todo app (9 modules, each with tests) and two cross-cutting features for the decomposition test.

Each feature touches 6-7 modules, so a single worker has to read and hold most of the codebase, while a
well-planned package only needs one or two files plus the interfaces it uses.
"""

TODO_FILES = {
    "conftest.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent / 'src'))\n",
    "src/todo/__init__.py": "",
    "src/todo/models.py": '''from dataclasses import dataclass, field


@dataclass
class Task:
    id: int
    title: str
    done: bool = False
    tags: list = field(default_factory=list)

    def to_dict(self):
        return {"id": self.id, "title": self.title, "done": self.done, "tags": list(self.tags)}

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], title=d["title"], done=d.get("done", False), tags=list(d.get("tags", [])))
''',
    "src/todo/storage.py": '''import json
from pathlib import Path

from todo.models import Task


class JsonStorage:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        return [Task.from_dict(d) for d in json.loads(self.path.read_text())]

    def save(self, tasks):
        self.path.write_text(json.dumps([t.to_dict() for t in tasks], indent=2))
''',
    "src/todo/ids.py": '''def next_id(tasks):
    return max((t.id for t in tasks), default=0) + 1
''',
    "src/todo/query.py": '''def filter_tasks(tasks, tag=None, include_done=True):
    out = []
    for t in tasks:
        if tag is not None and tag not in t.tags:
            continue
        if not include_done and t.done:
            continue
        out.append(t)
    return out
''',
    "src/todo/service.py": '''from todo.ids import next_id
from todo.models import Task
from todo.query import filter_tasks


class TodoService:
    def __init__(self, storage):
        self.storage = storage

    def add(self, title, tags=()):
        if not title.strip():
            raise ValueError("title must not be empty")
        tasks = self.storage.load()
        task = Task(id=next_id(tasks), title=title.strip(), tags=list(tags))
        tasks.append(task)
        self.storage.save(tasks)
        return task

    def complete(self, task_id):
        tasks = self.storage.load()
        for t in tasks:
            if t.id == task_id:
                t.done = True
                self.storage.save(tasks)
                return t
        raise KeyError(task_id)

    def delete(self, task_id):
        tasks = self.storage.load()
        kept = [t for t in tasks if t.id != task_id]
        if len(kept) == len(tasks):
            raise KeyError(task_id)
        self.storage.save(kept)

    def list(self, tag=None, include_done=True):
        return filter_tasks(self.storage.load(), tag=tag, include_done=include_done)
''',
    "src/todo/formatting.py": '''def format_task(task):
    box = "[x]" if task.done else "[ ]"
    tags = " " + " ".join(f"#{t}" for t in task.tags) if task.tags else ""
    return f"{task.id:>3} {box} {task.title}{tags}"


def format_list(tasks):
    if not tasks:
        return "No tasks."
    return "\\n".join(format_task(t) for t in tasks)
''',
    "src/todo/export.py": '''import csv
import io


def to_csv(tasks):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\\n")
    w.writerow(["id", "title", "done", "tags"])
    for t in tasks:
        w.writerow([t.id, t.title, t.done, ";".join(t.tags)])
    return buf.getvalue()


def to_markdown(tasks):
    return "\\n".join(f"- [{'x' if t.done else ' '}] {t.title}" for t in tasks)
''',
    "src/todo/stats.py": '''from collections import Counter


def completion_rate(tasks):
    if not tasks:
        return 0.0
    return sum(t.done for t in tasks) / len(tasks)


def counts_by_tag(tasks):
    return dict(Counter(tag for t in tasks for tag in t.tags))
''',
    "src/todo/cli.py": '''import argparse

from todo.formatting import format_list, format_task
from todo.service import TodoService
from todo.storage import JsonStorage


def build_parser():
    p = argparse.ArgumentParser(prog="todo")
    p.add_argument("--file", default="todo.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("title")
    a.add_argument("--tag", action="append", default=[])
    d = sub.add_parser("done")
    d.add_argument("id", type=int)
    ls = sub.add_parser("list")
    ls.add_argument("--tag")
    ls.add_argument("--pending", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    svc = TodoService(JsonStorage(args.file))
    if args.cmd == "add":
        return format_task(svc.add(args.title, tags=args.tag))
    if args.cmd == "done":
        return format_task(svc.complete(args.id))
    if args.cmd == "list":
        return format_list(svc.list(tag=args.tag, include_done=not args.pending))
''',
    "tests/test_models.py": '''from todo.models import Task


def test_roundtrip():
    t = Task(1, "a", tags=["x"])
    assert Task.from_dict(t.to_dict()) == t
''',
    "tests/test_storage.py": '''from todo.models import Task
from todo.storage import JsonStorage


def test_save_load(tmp_path):
    s = JsonStorage(tmp_path / "t.json")
    s.save([Task(1, "a")])
    assert s.load() == [Task(1, "a")]
''',
    "tests/test_service.py": '''import pytest

from todo.service import TodoService
from todo.storage import JsonStorage


def test_add_complete(tmp_path):
    svc = TodoService(JsonStorage(tmp_path / "t.json"))
    t = svc.add("  a  ", tags=["x"])
    assert t.id == 1 and t.title == "a"
    svc.complete(1)
    assert svc.list()[0].done
    with pytest.raises(ValueError):
        svc.add("  ")
''',
    "tests/test_query.py": '''from todo.models import Task
from todo.query import filter_tasks


def test_filter():
    ts = [Task(1, "a", tags=["x"]), Task(2, "b", done=True)]
    assert [t.id for t in filter_tasks(ts, tag="x")] == [1]
    assert [t.id for t in filter_tasks(ts, include_done=False)] == [1]
''',
    "tests/test_formatting.py": '''from todo.formatting import format_list, format_task
from todo.models import Task


def test_format():
    assert format_task(Task(1, "a", tags=["x"])) == "  1 [ ] a #x"
    assert format_list([]) == "No tasks."
''',
    "tests/test_export.py": '''from todo.export import to_csv, to_markdown
from todo.models import Task


def test_export():
    assert to_csv([Task(1, "a", tags=["x", "y"])]) == "id,title,done,tags\\n1,a,False,x;y\\n"
    assert to_markdown([Task(1, "a", done=True)]) == "- [x] a"
''',
    "tests/test_stats.py": '''from todo.models import Task
from todo.stats import completion_rate, counts_by_tag


def test_stats():
    ts = [Task(1, "a", done=True, tags=["x"]), Task(2, "b", tags=["x"])]
    assert completion_rate(ts) == 0.5 and counts_by_tag(ts) == {"x": 2}
''',
    "tests/test_cli.py": '''from todo.cli import main


def test_add_list(tmp_path):
    f = str(tmp_path / "c.json")
    main(["--file", f, "add", "milk", "--tag", "shop"])
    assert main(["--file", f, "list"]) == "  1 [ ] milk #shop"
''',
}

PRIORITY_DESCRIPTION = """Add task priorities across the app.

1. `src/todo/models.py`: Task gets a `priority` field, one of "low", "normal", "high", default "normal". Creating a Task with any other priority raises ValueError. to_dict/from_dict include priority, and from_dict of a dict with no "priority" key gives "normal" (files saved before this change must still load).
2. `src/todo/service.py`: TodoService.add(title, tags=(), priority="normal") passes the priority to the new Task (and it is saved).
3. `src/todo/query.py`: add sort_tasks(tasks, by="id") returning a new sorted list without changing the input. by="priority" sorts high, then normal, then low, ties broken by id ascending; by="title" sorts by title; by="id" by id. Any other `by` raises ValueError.
4. `src/todo/formatting.py`: format_task puts "!" immediately before the title of a high-priority task, e.g. "  1 [ ] !Buy milk". Other tasks format exactly as before.
5. `src/todo/export.py`: to_csv gets a priority column right after title; the header becomes "id,title,priority,done,tags".
6. `src/todo/stats.py`: add counts_by_priority(tasks) returning a dict with all three keys, e.g. {"high": 1, "normal": 2, "low": 0}.
7. `src/todo/cli.py`: `add` accepts `--priority {low,normal,high}` (default normal), and `list` accepts `--sort {id,priority,title}` (default id).
8. Update or add tests for each of these in the matching tests/test_<module>.py files.
"""

PRIORITY_ORACLE = '''import json
import pytest
from todo.models import Task
from todo.service import TodoService
from todo.storage import JsonStorage
from todo.query import sort_tasks
from todo.formatting import format_task
from todo.export import to_csv
from todo.stats import counts_by_priority
from todo.cli import main


def test_model_priority():
    assert Task(1, "a").priority == "normal"
    assert Task(1, "a", priority="high").priority == "high"
    with pytest.raises(ValueError):
        Task(1, "a", priority="urgent")


def test_roundtrip_and_old_files(tmp_path):
    assert Task.from_dict(Task(1, "a", priority="low").to_dict()).priority == "low"
    assert Task.from_dict({"id": 2, "title": "b"}).priority == "normal"
    p = tmp_path / "old.json"
    p.write_text(json.dumps([{"id": 1, "title": "x", "done": False, "tags": []}]))
    assert JsonStorage(p).load()[0].priority == "normal"


def test_service_priority(tmp_path):
    TodoService(JsonStorage(tmp_path / "t.json")).add("a", priority="high")
    assert TodoService(JsonStorage(tmp_path / "t.json")).list()[0].priority == "high"


def test_sort_tasks():
    ts = [Task(1, "c", priority="low"), Task(2, "a", priority="high"), Task(3, "b"), Task(4, "d", priority="high")]
    assert [t.id for t in sort_tasks(ts, "priority")] == [2, 4, 3, 1]
    assert [t.id for t in sort_tasks(ts, "title")] == [2, 3, 1, 4]
    assert [t.id for t in sort_tasks(list(reversed(ts)), "id")] == [1, 2, 3, 4]
    assert [t.id for t in ts] == [1, 2, 3, 4]
    with pytest.raises(ValueError):
        sort_tasks(ts, "due")


def test_format():
    assert format_task(Task(1, "Buy milk", priority="high")) == "  1 [ ] !Buy milk"
    assert format_task(Task(2, "Walk", tags=["home"])) == "  2 [ ] Walk #home"
    assert format_task(Task(3, "Low", priority="low")) == "  3 [ ] Low"


def test_csv():
    assert to_csv([Task(1, "a", priority="high", tags=["x", "y"])]) == "id,title,priority,done,tags\\n1,a,high,False,x;y\\n"


def test_counts_by_priority():
    assert counts_by_priority([Task(1, "a"), Task(2, "b", priority="high")]) == {"high": 1, "normal": 1, "low": 0}


def test_cli(tmp_path):
    f = str(tmp_path / "c.json")
    main(["--file", f, "add", "low one", "--priority", "low"])
    main(["--file", f, "add", "high one", "--priority", "high"])
    main(["--file", f, "add", "plain"])
    out = main(["--file", f, "list", "--sort", "priority"]).splitlines()
    assert "high one" in out[0] and "plain" in out[1] and "low one" in out[2]
    assert main(["--file", f, "list"]).splitlines()[0].endswith("low one")
'''

DUE_DESCRIPTION = """Add due dates and overdue tracking across the app.

1. New module `src/todo/dates.py`: parse_due(text, today) returns a datetime.date. It accepts "YYYY-MM-DD", "today", "tomorrow", and "+Nd" (N days after today, N a positive integer). Anything else raises ValueError.
2. `src/todo/models.py`: Task gets `due` (a datetime.date or None, default None). to_dict stores it as an ISO "YYYY-MM-DD" string or None; from_dict turns it back into a date, and a dict with no "due" key loads as None. Add Task.is_overdue(today): True only if the task is not done, has a due date, and the due date is before today.
3. `src/todo/service.py`: TodoService.add(title, tags=(), due=None, today=None): `due` is a string parsed with parse_due (today defaults to datetime.date.today()); the date is saved on the task.
4. `src/todo/query.py`: add overdue(tasks, today) returning the overdue tasks sorted by due date, ties by id.
5. `src/todo/formatting.py`: format_task(task, today=None): when today is given and the task is overdue, append " (overdue)" to the line. Without today, output is unchanged.
6. `src/todo/cli.py`: `add` accepts `--due TEXT`, and `list` accepts `--overdue`, which shows only tasks overdue as of today, formatted with the overdue marker.
7. Update or add tests for each of these in the matching tests/test_<module>.py files (tests/test_dates.py for the new module).
"""

DUE_ORACLE = '''import datetime as dt
import pytest
from todo.dates import parse_due
from todo.models import Task
from todo.service import TodoService
from todo.storage import JsonStorage
from todo.query import overdue
from todo.formatting import format_task
from todo.cli import main

D = dt.date
TODAY = D(2026, 3, 10)


def test_parse_due():
    assert parse_due("2026-04-01", TODAY) == D(2026, 4, 1)
    assert parse_due("today", TODAY) == TODAY
    assert parse_due("tomorrow", TODAY) == D(2026, 3, 11)
    assert parse_due("+3d", TODAY) == D(2026, 3, 13)
    assert parse_due("+30d", TODAY) == D(2026, 4, 9)
    for bad in ["next week", "2026-13-01", "+d", "", "3d"]:
        with pytest.raises(ValueError):
            parse_due(bad, TODAY)


def test_task_due_roundtrip():
    t = Task(1, "a", due=D(2026, 3, 1))
    assert t.to_dict()["due"] == "2026-03-01"
    assert Task.from_dict(t.to_dict()).due == D(2026, 3, 1)
    assert Task.from_dict({"id": 2, "title": "b"}).due is None
    assert Task(3, "c").to_dict()["due"] is None


def test_is_overdue():
    assert Task(1, "a", due=D(2026, 3, 9)).is_overdue(TODAY)
    assert not Task(1, "a", due=TODAY).is_overdue(TODAY)
    assert not Task(1, "a", done=True, due=D(2026, 3, 1)).is_overdue(TODAY)
    assert not Task(1, "a").is_overdue(TODAY)


def test_service_due(tmp_path):
    svc = TodoService(JsonStorage(tmp_path / "t.json"))
    assert svc.add("a", due="+2d", today=TODAY).due == D(2026, 3, 12)
    assert TodoService(JsonStorage(tmp_path / "t.json")).list()[0].due == D(2026, 3, 12)
    with pytest.raises(ValueError):
        svc.add("b", due="someday", today=TODAY)
    assert svc.add("c").due is None


def test_overdue_query():
    ts = [Task(1, "a", due=D(2026, 3, 5)), Task(2, "b", due=D(2026, 3, 1)), Task(3, "c", due=D(2026, 3, 20)),
          Task(4, "d"), Task(5, "e", done=True, due=D(2026, 1, 1)), Task(6, "f", due=D(2026, 3, 1))]
    assert [t.id for t in overdue(ts, TODAY)] == [2, 6, 1]


def test_format_overdue():
    t = Task(1, "Pay rent", due=D(2026, 3, 1))
    assert format_task(t) == "  1 [ ] Pay rent"
    assert format_task(t, today=TODAY) == "  1 [ ] Pay rent (overdue)"
    assert format_task(Task(2, "x", due=D(2026, 4, 1)), today=TODAY) == "  2 [ ] x"


def test_cli(tmp_path):
    f = str(tmp_path / "c.json")
    main(["--file", f, "add", "old", "--due", "2000-01-01"])
    main(["--file", f, "add", "future", "--due", "2999-01-01"])
    main(["--file", f, "add", "none"])
    out = main(["--file", f, "list", "--overdue"])
    assert "old" in out and "future" not in out and "none" not in out and "(overdue)" in out
'''
