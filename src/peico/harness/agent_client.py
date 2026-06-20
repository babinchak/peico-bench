"""The bench↔agent contract (in-process form).

An agent implementation is anything the bench can drive turn by turn. The bench
provisions a session :class:`Environment` and hands it to a **factory** the agent
exposes; the factory returns an :class:`AgentClient` bound to that environment.
The bench then calls ``welcome()`` (the rep speaks first) and ``respond(...)`` for
each customer turn (doc 08, "Session lifecycle").

There is no static dependency from the bench to any agent: the factory is resolved
at runtime by import path (``module:function``). Remotely, the same two calls
become HTTP requests to a registered agent endpoint — same contract, new wires.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from .environment import Environment


@dataclass
class AgentReply:
    """One rep turn: the message to the customer plus an optional terminate signal."""

    message: str
    terminate: bool = False
    trace: list | None = None  # opaque, optional, display-only


@runtime_checkable
class AgentClient(Protocol):
    def welcome(self) -> str:
        """Return the rep's opening message (the rep speaks first)."""
        ...

    def respond(self, customer_message: str) -> AgentReply:
        """Handle one customer turn and return the rep's reply."""
        ...


# A factory maps a session environment to a ready agent client.
AgentFactory = Callable[[Environment], AgentClient]
