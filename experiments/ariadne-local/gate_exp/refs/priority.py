"""Reference implementation of the priority feature (file -> new content), for oracle validation only."""
from todo_app import TODO_FILES as F
REF = {
"src/todo/models.py": '''from dataclasses import dataclass, field

PRIORITIES = ("low", "normal", "high")


@dataclass
class Task:
    id: int
    title: str
    done: bool = False
    tags: list = field(default_factory=list)
    priority: str = "normal"

    def __post_init__(self):
        if self.priority not in PRIORITIES:
            raise ValueError(self.priority)

    def to_dict(self):
        return {"id": self.id, "title": self.title, "done": self.done, "tags": list(self.tags), "priority": self.priority}

    @classmethod
    def from_dict(cls, d):
        return cls(id=d["id"], title=d["title"], done=d.get("done", False), tags=list(d.get("tags", [])),
                   priority=d.get("priority", "normal"))
''',
"src/todo/service.py": F["src/todo/service.py"].replace("def add(self, title, tags=()):", 'def add(self, title, tags=(), priority="normal"):').replace("tags=list(tags))", "tags=list(tags), priority=priority)"),
"src/todo/query.py": F["src/todo/query.py"] + '''

RANK = {"high": 0, "normal": 1, "low": 2}


def sort_tasks(tasks, by="id"):
    keys = {"id": lambda t: t.id, "title": lambda t: t.title, "priority": lambda t: (RANK[t.priority], t.id)}
    if by not in keys:
        raise ValueError(by)
    return sorted(tasks, key=keys[by])
''',
"src/todo/formatting.py": F["src/todo/formatting.py"].replace('return f"{task.id:>3} {box} {task.title}{tags}"', 'bang = "!" if task.priority == "high" else ""\n    return f"{task.id:>3} {box} {bang}{task.title}{tags}"'),
"src/todo/export.py": F["src/todo/export.py"].replace('["id", "title", "done", "tags"]', '["id", "title", "priority", "done", "tags"]').replace("[t.id, t.title, t.done,", "[t.id, t.title, t.priority, t.done,"),
"src/todo/stats.py": F["src/todo/stats.py"] + '''

def counts_by_priority(tasks):
    out = {"high": 0, "normal": 0, "low": 0}
    for t in tasks:
        out[t.priority] += 1
    return out
''',
"src/todo/cli.py": F["src/todo/cli.py"].replace('a.add_argument("--tag", action="append", default=[])', 'a.add_argument("--tag", action="append", default=[])\n    a.add_argument("--priority", choices=["low", "normal", "high"], default="normal")').replace('ls.add_argument("--pending", action="store_true")', 'ls.add_argument("--pending", action="store_true")\n    ls.add_argument("--sort", choices=["id", "priority", "title"], default="id")').replace("svc.add(args.title, tags=args.tag)", "svc.add(args.title, tags=args.tag, priority=args.priority)").replace("return format_list(svc.list(tag=args.tag, include_done=not args.pending))", "from todo.query import sort_tasks\n        return format_list(sort_tasks(svc.list(tag=args.tag, include_done=not args.pending), args.sort))"),
"tests/test_export.py": F["tests/test_export.py"].replace("id,title,done,tags\\\\n1,a,False", "id,title,priority,done,tags\\\\n1,a,normal,False"),
}
