"""The environment service: what an agent is given access to for one session.

This is the *only* surface an agent touches. It never holds the database; it
issues calls against this handle, which the bench scopes to one session's world:

    query(sql)          read-only SQL over the session world
    write(sql)          mutate the session world; returns the resulting changeset
    rate(facts, as_of)  the canonical physics (the bench's rating engine)
    search_kb(q)        convenience search over the kb_documents wiki

Raw SQL is allowed on both reads and writes (design principle 9): rule enforcement
lives in the expected outcome, not the write path. Every call returns a plain
JSON-serializable dict — successes and structured errors alike — so the agent can
read an error and recover. Errors are never raised across this boundary.

Transport-agnostic by construction: locally the agent calls these methods
directly (object injection); the same shapes go over HTTP later (doc 08).
"""
from __future__ import annotations

import re

from peico import rating

from . import changeset as cs

_MAX_ROWS = 200

# query is read-only: SELECT/WITH only, single statement.
_READ_OK = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_READ_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b",
    re.IGNORECASE,
)
# write forbids only cross-database / pragma escapes; INSERT/UPDATE/DELETE/DDL are
# all fair game — landing the wrong rows just fails the changeset.
_WRITE_FORBIDDEN = re.compile(r"\b(attach|detach|pragma)\b", re.IGNORECASE)


def _one_statement(sql: str) -> str | None:
    stripped = sql.strip().rstrip(";")
    return stripped if ";" not in stripped else None


class Environment:
    """A session-scoped handle over one :class:`World`."""

    def __init__(self, world, *, capabilities: tuple[str, ...] = ("query", "write", "rate", "search_kb")):
        self.world = world
        self.capabilities = list(capabilities)

    @property
    def anchor_date(self) -> str:
        return self.world.anchor_date

    # -- reads ----------------------------------------------------------------

    def query(self, sql: str) -> dict:
        """Run a read-only SQL query; return rows or a structured error."""
        stmt = _one_statement(sql)
        if stmt is None:
            return {"error": "one_statement_only"}
        if not _READ_OK.match(stmt) or _READ_FORBIDDEN.search(stmt):
            return {"error": "read_only", "detail": "Only SELECT/WITH queries are allowed."}
        con = self.world.connect(writable=False)
        try:
            rows = [dict(r) for r in con.execute(stmt).fetchmany(_MAX_ROWS + 1)]
        except Exception as exc:  # noqa: BLE001 — SQL errors are feedback for the agent
            return {"error": "sql_error", "detail": str(exc)}
        finally:
            con.close()
        truncated = len(rows) > _MAX_ROWS
        return {
            "rows": rows[:_MAX_ROWS],
            "row_count": min(len(rows), _MAX_ROWS),
            "truncated": truncated,
        }

    def search_kb(self, query: str, limit: int = 8) -> dict:
        """Keyword search over the policy wiki (kb_documents)."""
        terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
        if not terms:
            return {"results": []}
        con = self.world.connect(writable=False)
        try:
            docs = con.execute(
                "SELECT doc_id, title, category, applies_to, body_md FROM kb_documents"
            ).fetchall()
        except Exception as exc:  # noqa: BLE001
            return {"error": "sql_error", "detail": str(exc)}
        finally:
            con.close()
        scored = []
        for d in docs:
            body = d["body_md"] or ""
            hay = f"{d['title']} {d['category']} {body}".lower()
            score = sum(hay.count(t) for t in terms)
            if score:
                scored.append((score, d, body))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [
            {
                "doc_id": d["doc_id"],
                "title": d["title"],
                "category": d["category"],
                "applies_to": d["applies_to"],
                "snippet": (body[:240] + "…") if len(body) > 240 else body,
            }
            for _, d, body in scored[: max(1, limit)]
        ]
        return {"results": results}

    # -- physics --------------------------------------------------------------

    def rate(self, facts: dict, as_of: str | None = None) -> dict:
        """Price a policy via the bench's canonical rating engine."""
        when = as_of or self.world.anchor_date
        try:
            result = rating.price(facts, when, self.world.rating_context())
        except Exception as exc:  # noqa: BLE001 — missing/invalid facts are feedback
            return {"error": "rate_failed", "detail": str(exc)}
        return {"as_of": when, **result}

    # -- writes ---------------------------------------------------------------

    def write(self, sql: str) -> dict:
        """Mutate the session world; return the changeset this write produced.

        The changeset (this write's before→after diff) is feedback for the agent —
        independent of final grading, which diffs the whole session seed→final.
        """
        if not self.world.writable:
            return {"error": "read_only_world"}
        stmt = _one_statement(sql)
        if stmt is None:
            return {"error": "one_statement_only"}
        if _WRITE_FORBIDDEN.search(stmt):
            return {"error": "forbidden", "detail": "attach/detach/pragma are not allowed."}
        con = self.world.connect(writable=True)
        try:
            before = cs.snapshot(con)
            cur = con.execute(stmt)
            rowcount = cur.rowcount
            con.commit()
            after = cs.snapshot(con)
        except Exception as exc:  # noqa: BLE001 — SQL errors are feedback
            con.rollback()
            return {"error": "sql_error", "detail": str(exc)}
        finally:
            con.close()
        return {"ok": True, "rows_affected": rowcount, "changeset": cs.diff(before, after)}
