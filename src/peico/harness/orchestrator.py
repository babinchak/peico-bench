"""Run one rollout: rep (agent) ↔ customer (simulator) over a session environment.

The turn protocol (doc 08):
  1. the rep speaks first — ``agent.welcome()``;
  2. then, up to ``max_turns``: the customer reacts, the rep responds;
  3. the rep ends the conversation voluntarily via ``terminate`` (it also speaks
     last). Hitting ``max_turns`` without terminate marks the session incomplete.

The orchestrator makes no judgments — it only drives turns and captures the
transcript. Grading happens afterward against the final world + transcript.
"""
from __future__ import annotations

from dataclasses import dataclass

from .simulator import UserSimulator


@dataclass
class Rollout:
    transcript: list      # list of (role, text): role in {"customer", "rep"}
    turns: int
    stopped_reason: str    # "agent_terminated" | "customer_done" | "max_turns"
    completed: bool        # True only if the agent terminated voluntarily


def run_rollout(task, env, make_agent, sim_model, *, on_event=None) -> Rollout:
    agent = make_agent(env)
    sim = UserSimulator(sim_model, task.persona)

    transcript: list = []

    # 1. The rep speaks first.
    welcome = agent.welcome()
    transcript.append(("rep", welcome))
    if on_event:
        on_event("rep", welcome)

    reason = "max_turns"
    for _ in range(task.max_turns):
        # 2a. The customer reacts to the latest rep message.
        customer, customer_done = sim.say(transcript)
        if customer:
            transcript.append(("customer", customer))
            if on_event:
                on_event("customer", customer)

        # 2b. The rep responds (and may terminate).
        reply = agent.respond(customer)
        transcript.append(("rep", reply.message))
        if on_event:
            on_event("rep", reply.message)

        if reply.terminate:
            reason = "agent_terminated"
            break
        if customer_done:
            reason = "customer_done"
            break

    return Rollout(transcript, len(transcript), reason, completed=(reason == "agent_terminated"))
