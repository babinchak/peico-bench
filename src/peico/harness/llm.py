"""LiteLLM client for the bench-owned models: the customer simulator and judge.

These models are part of the benchmark, not the system under test — the bench
owns and powers them (the keystone of honesty). LiteLLM gives one OpenAI-shaped
interface across providers, so the pinned model is a string. Usage is tracked for
diagnostics only; cost/latency are never part of grading.
"""
from __future__ import annotations

from dataclasses import dataclass

import litellm

litellm.drop_params = True

_EPHEMERAL = {"type": "ephemeral"}


def _is_anthropic(name: str) -> bool:
    n = name.lower()
    return "claude" in n or n.startswith("anthropic/")


def _text_block(text: str) -> list[dict]:
    return [{"type": "text", "text": text, "cache_control": _EPHEMERAL}]


def _with_cache(messages: list[dict]) -> list[dict]:
    """Cache breakpoints on the (large, repeated) system prompt and the last turn."""
    out = list(messages)
    for i, m in enumerate(out):
        if m.get("role") == "system" and isinstance(m.get("content"), str) and m["content"]:
            out[i] = {**m, "content": _text_block(m["content"])}
            break
    last = out[-1] if out else None
    if last and last.get("role") in ("user", "tool") and isinstance(last.get("content"), str) and last["content"]:
        out[-1] = {**last, "content": _text_block(last["content"])}
    return out


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def __str__(self) -> str:
        s = (
            f"{self.calls} calls · {self.prompt_tokens} in / "
            f"{self.completion_tokens} out tokens · ${self.cost_usd:.4f}"
        )
        if self.cache_read_tokens or self.cache_write_tokens:
            s += f" · cache {self.cache_read_tokens} read / {self.cache_write_tokens} write"
        return s


class Model:
    """A single model behind LiteLLM, accumulating usage across the run."""

    def __init__(self, name: str):
        self.name = name
        self.usage = Usage()

    def complete(self, messages: list[dict]):
        """One model turn (no tools — sim/judge don't use them). Returns the message."""
        msgs = _with_cache(messages) if _is_anthropic(self.name) else messages
        resp = litellm.completion(model=self.name, messages=msgs)
        self._track(resp)
        return resp.choices[0].message

    def _track(self, resp) -> None:
        self.usage.calls += 1
        u = getattr(resp, "usage", None)
        if u:
            self.usage.prompt_tokens += getattr(u, "prompt_tokens", 0) or 0
            self.usage.completion_tokens += getattr(u, "completion_tokens", 0) or 0
            self.usage.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
            self.usage.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        try:
            self.usage.cost_usd += litellm.completion_cost(resp) or 0.0
        except Exception:  # noqa: BLE001 — cost map may not cover every model
            pass
