from __future__ import annotations

from textual.widgets import Static

from .panel import Panel

ICONS = {"in_progress": "[>]", "pending": "[ ]", "done": "[x]"}


def task_rows(active: dict) -> list[str]:
    tasks = active.get("tasks", []) if active else []
    ordered = [t for t in tasks if t.get("status") == "in_progress"] + [t for t in tasks if t.get("status") == "pending"]
    return [f"{ICONS.get(t.get('status'), '[ ]')} {t.get('id', '')}  {t.get('title', '')}" for t in ordered]


class Gameplan(Panel):
    """◆Gameplan: the active phase's open tasks, in progress first. Done is hidden."""

    card = "Gameplan"
    DEFAULT_CSS = """
    Gameplan {
        height: 1fr;
        min-height: 4;
    }
    Gameplan .title { text-style: bold; }
    """

    def compose(self):
        yield Static("Gameplan", classes="title", id="plan-title")
        yield Static("", id="plan-body")

    def refresh_state(self, state) -> None:
        active = (state.gameplan or {}).get("activePhase") or {}
        tasks = active.get("tasks", [])
        done = sum(1 for t in tasks if t.get("status") == "done")
        tag = f"{active.get('id', '')} · {done}/{len(tasks)}" if active else ""
        self.query_one("#plan-title", Static).update(f"Gameplan  {tag}")
        rows = task_rows(active)
        if not active:
            body = ("No active phase.\nA phase groups work; its tasks are what's next.\n"
                    "Start one: daedalus gameplan phase activate <id>")
        elif not rows:
            body = "Every task in this phase is done.\nMark the phase done, or add the next task."
        else:
            body = "\n".join(rows)
        self.query_one("#plan-body", Static).update(body)
