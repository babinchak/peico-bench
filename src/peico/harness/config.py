"""Harness configuration: where the world lives and which models power grading.

The bench owns and powers the customer simulator and the LLM judge, so their
model strings live here, not in any agent. Paths are resolved relative to the
installed ``peico`` package so the harness works whether it's run from a source
checkout or an editable install in another project's venv.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # pull .env into the environment if present

# Repo root = two levels above this package dir (src/peico/harness -> repo).
_REPO_ROOT = Path(__file__).resolve().parents[3]

# "Today" in the world. Promotions and rate versions resolve against this date.
# MUST match build_reference.py's WORLD_ANCHOR_DATE, or pricing will disagree.
WORLD_ANCHOR_DATE = "2025-06-01"


def _resolve_seed_db() -> Path:
    env = os.getenv("PEICO_DB_PATH")
    if env:
        return Path(env).expanduser().resolve()
    return _REPO_ROOT / "out" / "peico.sqlite"


@dataclass(frozen=True)
class HarnessSettings:
    seed_db: Path
    anchor_date: str = WORLD_ANCHOR_DATE
    # The simulator and judge are part of the bench, not the system under test, so
    # they default to a cheap, pinned model. Override per run via env / CLI.
    sim_model: str = "anthropic/claude-haiku-4-5"
    judge_model: str = "anthropic/claude-haiku-4-5"
    tasks_dir: Path = _REPO_ROOT / "tasks"

    def require_world(self) -> None:
        if not self.seed_db.exists():
            raise SystemExit(
                f"World DB not found at {self.seed_db}\n"
                f"Build it first:\n"
                f"  python src/peico/build_reference.py && python src/peico/generate.py"
            )


def load_settings() -> HarnessSettings:
    return HarnessSettings(
        seed_db=_resolve_seed_db(),
        sim_model=os.getenv("PEICO_SIM_MODEL", "anthropic/claude-haiku-4-5"),
        judge_model=os.getenv("PEICO_JUDGE_MODEL", "anthropic/claude-haiku-4-5"),
    )


settings = load_settings()
