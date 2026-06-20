"""Pure database diff: the deterministic backbone of changeset grading.

`snapshot(con)` reads a database into a plain dict keyed by primary key, and
`diff(before, after)` produces a structured changeset:

    {table: {added: [...], removed: [...], changed: [{pk, fields: {col: [old, new]}}]}}

Both are pure (no I/O beyond the passed connection), so the grading verdict is
fully reproducible. The diff is row/value level, not byte level, so an unchanged
session yields an empty changeset even though the seed was physically copied.
"""
from __future__ import annotations

import sqlite3


def _tables(con: sqlite3.Connection) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _pk_cols(con: sqlite3.Connection, table: str) -> list[str]:
    info = list(con.execute(f"PRAGMA table_info('{table}')"))
    pks = [r["name"] for r in sorted(info, key=lambda r: r["pk"]) if r["pk"]]
    # No declared PK: treat the whole row as its identity so changes still surface.
    return pks or [r["name"] for r in info]


def snapshot(con: sqlite3.Connection) -> dict:
    """Read every user table into {table: {"pks": [...], "rows": {key: row_dict}}}."""
    con.row_factory = sqlite3.Row
    snap: dict = {}
    for table in _tables(con):
        pks = _pk_cols(con, table)
        rows: dict = {}
        for r in con.execute(f"SELECT * FROM '{table}'"):
            row = dict(r)
            key = tuple(str(row[c]) for c in pks)
            rows[key] = row
        snap[table] = {"pks": pks, "rows": rows}
    return snap


def diff(before: dict, after: dict) -> dict:
    """Structured changeset between two snapshots."""
    out: dict = {}
    for table in sorted(set(before) | set(after)):
        b = before.get(table, {"pks": [], "rows": {}})
        a = after.get(table, {"pks": [], "rows": {}})
        pks = a["pks"] or b["pks"]
        brows, arows = b["rows"], a["rows"]

        added = [{"pk": _pk_obj(pks, k), "row": arows[k]} for k in arows.keys() - brows.keys()]
        removed = [{"pk": _pk_obj(pks, k), "row": brows[k]} for k in brows.keys() - arows.keys()]
        changed = []
        for k in arows.keys() & brows.keys():
            fields = {
                col: [brows[k].get(col), arows[k].get(col)]
                for col in arows[k]
                if brows[k].get(col) != arows[k].get(col)
            }
            if fields:
                changed.append({"pk": _pk_obj(pks, k), "fields": fields})

        entry = {}
        if added:
            entry["added"] = added
        if removed:
            entry["removed"] = removed
        if changed:
            entry["changed"] = changed
        if entry:
            out[table] = entry
    return out


def _pk_obj(pks: list[str], key: tuple) -> dict:
    return {pks[i]: key[i] for i in range(len(pks))} if pks else {"_row": list(key)}
