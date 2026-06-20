"""What a task is, and how to load one from YAML (bench-side, never sent to the agent).

A task is a self-contained eval case: the persona that drives the customer
simulator (profile / knowledge / reactions / goal), any per-session setup SQL,
a turn budget, and the checks that grade the outcome. See doc 08 for the schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Persona:
    name: str
    goal: str               # the customer's success intent (drives the sim, not the grader)
    profile: str = ""       # hidden context that shapes behavior, not stated outright
    knowledge: str = ""     # what the customer will say / reveal if relevant
    reactions: str = ""     # how to react to what the rep surfaces (incl. forgotten holdings)


@dataclass
class Task:
    task_id: str
    persona: Persona
    checks: list                                 # list of check spec dicts (see checks.build_check)
    max_turns: int = 8
    setup: list = field(default_factory=list)    # SQL applied to the session copy first

    @property
    def has_changeset_check(self) -> bool:
        return any(c.get("type") == "changeset" for c in self.checks)


def load_task(path: str | Path) -> Task:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    p = data["persona"]
    return Task(
        task_id=data["task_id"],
        persona=Persona(
            name=p["name"],
            goal=p["goal"],
            profile=p.get("profile", ""),
            knowledge=p.get("knowledge", ""),
            reactions=p.get("reactions", ""),
        ),
        checks=data.get("checks", []),
        max_turns=int(data.get("max_turns", 8)),
        setup=data.get("setup", []),
    )
