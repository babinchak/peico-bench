"""The PEICO evaluation harness: world, environment service, simulator, grading.

Public API for an agent implementation and for running the bench:

- :class:`~peico.harness.environment.Environment` — the per-session handle an
  agent is given (``query`` / ``write`` / ``rate`` / ``search_kb``).
- :class:`~peico.harness.agent_client.AgentClient` / ``AgentReply`` / ``AgentFactory``
  — the contract an agent implements; the bench calls ``welcome`` / ``respond``.
- :class:`~peico.harness.world.World` — per-session isolated database.
- :func:`~peico.harness.task.load_task`, :func:`~peico.harness.runner.run_trial`.
"""
from __future__ import annotations

from .agent_client import AgentClient, AgentFactory, AgentReply
from .environment import Environment
from .task import Persona, Task, load_task
from .world import World

__all__ = [
    "AgentClient",
    "AgentFactory",
    "AgentReply",
    "Environment",
    "World",
    "Task",
    "Persona",
    "load_task",
]
