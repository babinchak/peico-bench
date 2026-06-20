"""The user simulator: a bench-owned LLM playing the customer.

A separate model + persona from the agent (the bench owns and powers it, so the
agent can't fabricate customer turns). The rep speaks first, so by the time the
simulator is asked for a line the transcript already holds the rep's opening; from
the customer's POV the rep's turns are the "user" role and its own are "assistant".

It produces one short, natural message per turn, pursuing its goal and reacting to
what the rep surfaces per its reaction rules. Termination is primarily the agent's
job (it closes the conversation), but the customer may end its final message with
[[DONE]] when satisfied or when giving up, which lets the loop stop early.
"""
from __future__ import annotations

from .task import Persona

DONE = "[[DONE]]"

_SIM_SYS = """You are role-playing a CUSTOMER contacting PEICO insurance support over chat. \
You are the customer, NOT the agent — never act as the rep.

Rules:
- Speak only as the customer, one short, natural message at a time.
- Pursue your goal. Provide details when asked, but only details you actually have.
- Do not invent account facts beyond what you're given; if you don't know something, say so.
- Follow your reaction rules when the rep surfaces something relevant.
- When your goal has been accomplished (the rep confirms it's done), or it's clearly \
impossible and you'd give up, thank the rep and end that final message with the token {done}.
- Keep it realistic and concise. No stage directions or narration.""".format(done=DONE)

_PERSONA_TMPL = """Your character:
Name: {name}
{profile}

Your goal:
{goal}

What you know / will reveal if relevant:
{knowledge}

How you react to what the rep does:
{reactions}"""


class UserSimulator:
    def __init__(self, model, persona: Persona):
        self.model = model
        self.persona = persona

    def _messages(self, transcript: list) -> list[dict]:
        system = _SIM_SYS + "\n\n" + _PERSONA_TMPL.format(
            name=self.persona.name,
            profile=self.persona.profile or "(no extra profile)",
            goal=self.persona.goal,
            knowledge=self.persona.knowledge or "(nothing specific)",
            reactions=self.persona.reactions or "(react naturally)",
        )
        msgs = [{"role": "system", "content": system}]
        for role, text in transcript:
            # Flip roles: the customer's own turns are "assistant" from its POV.
            msgs.append({"role": "assistant" if role == "customer" else "user", "content": text})
        if not transcript:
            msgs.append(
                {"role": "user", "content": "(Begin the conversation: greet the rep and say what you need.)"}
            )
        return msgs

    def say(self, transcript: list) -> tuple[str, bool]:
        """Return (customer_message, done)."""
        msg = self.model.complete(self._messages(transcript))
        text = (msg.content or "").strip()
        done = DONE in text
        return text.replace(DONE, "").strip(), done
