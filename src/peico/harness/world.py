"""Per-session world: an isolated, writable copy of the seed database.

The canonical ``out/peico.sqlite`` is treated as a read-only *seed*. Each session
gets its own copy via ``World.from_seed()`` so sessions are completely independent
and writable without touching the seed or each other — which is also what makes
parallel/concurrent runs safe (every session is its own file, no shared mutable
state, no cross-session locking).

The world also holds the per-session rating *context*, built from this session's
own database, so the physics engine and the database can never disagree (design
principle 8/10). The engine itself is imported, never reimplemented.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from peico import rating

from .config import settings


def _missing_db(path: Path) -> SystemExit:
    return SystemExit(
        f"World DB not found at {path}\n"
        f"Build it first:\n"
        f"  python src/peico/build_reference.py && python src/peico/generate.py"
    )


class World:
    """A handle to one session's database (plus its rating context)."""

    def __init__(self, db_path: Path, anchor_date: str, *, writable: bool, _tmp: str | None = None):
        self.db_path = Path(db_path)
        self.anchor_date = anchor_date
        self.writable = writable
        self._tmp = _tmp  # temp dir to remove on cleanup, if this World owns one
        self._rating_ctx = None

    # -- construction ---------------------------------------------------------

    @classmethod
    def open(cls, db_path: Path | str | None = None, *, anchor_date: str | None = None,
             writable: bool = False) -> "World":
        """Open an existing database in place (read-only by default)."""
        path = Path(db_path) if db_path is not None else settings.seed_db
        if not path.exists():
            raise _missing_db(path)
        return cls(path, anchor_date or settings.anchor_date, writable=writable)

    @classmethod
    def from_seed(cls, seed_path: Path | str | None = None, *, anchor_date: str | None = None) -> "World":
        """Copy the seed DB to a private temp file → an isolated, writable session."""
        seed = Path(seed_path) if seed_path is not None else settings.seed_db
        if not seed.exists():
            raise _missing_db(seed)
        tmp = tempfile.mkdtemp(prefix="peico-session-")
        dst = Path(tmp) / "world.sqlite"
        shutil.copy2(seed, dst)
        return cls(dst, anchor_date or settings.anchor_date, writable=True, _tmp=tmp)

    # -- access ---------------------------------------------------------------

    def connect(self, *, writable: bool | None = None) -> sqlite3.Connection:
        """A fresh connection to this session's DB.

        Reads default to a read-only connection even on a writable world, so the
        ``query`` path can never mutate; ``write`` opts in explicitly.
        """
        want_write = self.writable if writable is None else writable
        if want_write:
            con = sqlite3.connect(str(self.db_path))
        else:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    def rating_context(self):
        """The reference snapshot this session's pricing engine reads (cached)."""
        if self._rating_ctx is None:
            self._rating_ctx = rating.load_context(self.db_path)
        return self._rating_ctx

    # -- lifecycle ------------------------------------------------------------

    def cleanup(self) -> None:
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None
            self._rating_ctx = None

    def __enter__(self) -> "World":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()
