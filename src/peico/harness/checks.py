"""Grading checks. A task carries a list; the runner ANDs the required ones.

Two gates (design principle 5):
  - ChangesetCheck — grades STATE: does the session seed→final DB diff equal the
    expected changeset (both "the right thing changed" and "nothing else did").
    Deterministic and free; present whenever a task changes state.
  - JudgeCheck — grades the CONVERSATION via a pinned LLM judge against a rubric.
    Runs on every task; stochastic, so flagged for the leaderboard.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import changeset as cs


@dataclass
class Verdict:
    name: str
    passed: bool
    detail: str = ""
    required: bool = True
    stochastic: bool = False


@dataclass
class GradeContext:
    """Everything a check might need to render a verdict."""

    task: object
    transcript: list           # list of (role, text): role in {"customer", "rep"}
    baseline: dict             # snapshot before the rollout (after task setup)
    final: dict                # snapshot after the rollout
    judge_model: object = None  # shared bench Model for JudgeCheck, if provided


# --------------------------------------------------------------------------- #
# Changeset check
# --------------------------------------------------------------------------- #
@dataclass
class ChangesetCheck:
    expected: dict
    required: bool = True
    name: str = "changeset"

    def run(self, ctx: GradeContext) -> Verdict:
        actual = cs.diff(ctx.baseline, ctx.final)
        if _changeset_key(actual) == _changeset_key(self.expected):
            return Verdict(self.name, True, "DB end-state matches the expected changeset.", self.required)
        detail = (
            "DB end-state did not match.\n"
            f"  expected: {json.dumps(self.expected, default=str)}\n"
            f"  actual:   {json.dumps(actual, default=str)}"
        )
        return Verdict(self.name, False, detail, self.required)


def _changeset_key(changeset: dict):
    """Order-insensitive comparison key, but preserving [old, new] delta order."""
    key = {}
    for table, entry in changeset.items():
        for op in ("added", "removed"):
            for item in entry.get(op, []):
                key[(table, op, _pk_key(item["pk"]))] = _row_key(item.get("row"))
        for item in entry.get("changed", []):
            key[(table, "changed", _pk_key(item["pk"]))] = tuple(
                (col, tuple(str(x) for x in delta)) for col, delta in sorted(item["fields"].items())
            )
    return key


def _pk_key(pk: dict):
    return tuple(sorted((str(k), str(v)) for k, v in pk.items()))


def _row_key(row):
    return tuple(sorted((str(k), str(v)) for k, v in (row or {}).items()))


# --------------------------------------------------------------------------- #
# Judge check
# --------------------------------------------------------------------------- #
_JUDGE_SYS = (
    "You are a strict grader for a customer-service conversation. You judge ONLY "
    "whether the rep's behavior satisfies the given rubric, based solely on the "
    "transcript. Do not invent facts. Respond with a single JSON object: "
    '{"passed": true|false, "reason": "<one sentence>"}.'
)

_JUDGE_TMPL = """RUBRIC (what the rep must have done):
{rubric}

REFERENCE ANSWER (for comparison, may be "(none)"):
{gold}

TRANSCRIPT:
{transcript}

Does the transcript satisfy the rubric? Reply with the JSON object only."""


@dataclass
class JudgeCheck:
    rubric: str
    gold: str | None = None
    required: bool = True
    model: str | None = None
    name: str = "judge"

    def run(self, ctx: GradeContext) -> Verdict:
        judge = ctx.judge_model or self._make_model()
        convo = "\n".join(f"{'CUSTOMER' if r == 'customer' else 'REP'}: {t}" for r, t in ctx.transcript)
        prompt = _JUDGE_TMPL.format(rubric=self.rubric, gold=self.gold or "(none)", transcript=convo)
        msg = judge.complete(
            [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": prompt}]
        )
        verdict = _parse_json(msg.content or "")
        passed = bool(verdict.get("passed"))
        reason = verdict.get("reason", "(judge returned no reason)")
        return Verdict(self.name, passed, f"judge: {reason}", self.required, stochastic=True)

    def _make_model(self):
        from .config import settings
        from .llm import Model

        return Model(self.model or settings.judge_model)


def _parse_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {"passed": False, "reason": "could not parse judge output"}


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def build_check(spec: dict):
    kind = spec.get("type")
    if kind == "changeset":
        return ChangesetCheck(expected=spec["expected"], required=spec.get("required", True))
    if kind == "judge":
        return JudgeCheck(
            rubric=spec["rubric"],
            gold=spec.get("gold"),
            required=spec.get("required", True),
            model=spec.get("model"),
        )
    raise ValueError(f"unknown check type: {kind!r}")
