"""Reference implementation of the due-date feature, for oracle validation only."""
from todo_app import TODO_FILES as F
REF = {
"src/todo/dates.py": '''import datetime as dt
import re


def parse_due(text, today):
    if text == "today":
        return today
    if text == "tomorrow":
        return today + dt.timedelta(days=1)
    m = re.fullmatch(r"\\+(\\d+)d", text)
    if m and int(m.group(1)) > 0:
        return today + dt.timedelta(days=int(m.group(1)))
    if re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", text):
        return dt.date.fromisoformat(text)
    raise ValueError(text)
''',
"src/todo/models.py": '''import datetime as dt
from dataclasses import dataclass, field


@dataclass
class Task:
    id: int
    title: str
    done: bool = False
    tags: list = field(default_factory=list)
    due: dt.date = None

    def is_overdue(self, today):
        return not self.done and self.due is not None and self.due < today

    def to_dict(self):
        return {"id": self.id, "title": self.title, "done": self.done, "tags": list(self.tags),
                "due": self.due.isoformat() if self.due else None}

    @classmethod
    def from_dict(cls, d):
        due = d.get("due")
        return cls(id=d["id"], title=d["title"], done=d.get("done", False), tags=list(d.get("tags", [])),
                   due=dt.date.fromisoformat(due) if due else None)
''',
"src/todo/service.py": F["src/todo/service.py"].replace("from todo.ids import next_id", "import datetime as dt\n\nfrom todo.dates import parse_due\nfrom todo.ids import next_id").replace("def add(self, title, tags=()):", "def add(self, title, tags=(), due=None, today=None):").replace("tags=list(tags))", "tags=list(tags),\n                    due=parse_due(due, today or dt.date.today()) if due is not None else None)"),
"src/todo/query.py": F["src/todo/query.py"] + '''

def overdue(tasks, today):
    return sorted((t for t in tasks if t.is_overdue(today)), key=lambda t: (t.due, t.id))
''',
"src/todo/formatting.py": F["src/todo/formatting.py"].replace("def format_task(task):", "def format_task(task, today=None):").replace('return f"{task.id:>3} {box} {task.title}{tags}"', 'late = " (overdue)" if today is not None and task.is_overdue(today) else ""\n    return f"{task.id:>3} {box} {task.title}{tags}{late}"'),
"src/todo/cli.py": F["src/todo/cli.py"].replace("import argparse", "import argparse\nimport datetime as dt").replace('a.add_argument("--tag", action="append", default=[])', 'a.add_argument("--tag", action="append", default=[])\n    a.add_argument("--due")').replace('ls.add_argument("--pending", action="store_true")', 'ls.add_argument("--pending", action="store_true")\n    ls.add_argument("--overdue", action="store_true")').replace("svc.add(args.title, tags=args.tag)", "svc.add(args.title, tags=args.tag, due=args.due)").replace("    if args.cmd == \"list\":\n", "    if args.cmd == \"list\" and args.overdue:\n        from todo.query import overdue\n        today = dt.date.today()\n        tasks = overdue(svc.list(tag=args.tag), today)\n        return \"\\\\n\".join(format_task(t, today=today) for t in tasks) or \"No tasks.\"\n    if args.cmd == \"list\":\n"),
}
