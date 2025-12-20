"""
Icarus Worker - Headless Claude Agent SDK harness.

Runs Claude Code in headless mode with permission requests routed through the bus.
"""

from .harness import IcarusWorker, run_worker

__all__ = ["IcarusWorker", "run_worker"]
