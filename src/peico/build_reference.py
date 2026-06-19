"""Build the PEICO reference database from the hand-authored YAML in data/reference/.

  python src/peico/build_reference.py

Outputs (gitignored, rebuilt from source):
  out/peico.sqlite   canonical SQLite (money in integer cents)
  out/peico.json     readable export for review / the website visualizer

This is the reference-tables stage only (the designed "physics"). Generated
entities (customers, policies, ledgers) are a later stage. Everything here is
hand-authored and reviewed like code (docs/04-data-generation.md).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "data" / "reference"
OUT = ROOT / "out"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"

WORLD_ANCHOR_DATE = "2025-06-01"  # "today" for the snapshot; promos resolve against it


def load(name: str):
    with open(REF / f"{name}.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def s(v):
    """Stringify YAML scalars (dates -> ISO) for storage; pass through None."""
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


def j(v):
    """JSON-encode a structured value for a TEXT(json) column; None stays None."""
    return None if v is None else json.dumps(v, default=s, ensure_ascii=False)


def canon_value(unit: str, val):
    """Canonicalize a default coverage value: money -> cents, else stringified."""
    if val is None:
        return None
    if unit in ("usd", "usd_daily"):
        return str(int(round(float(val) * 100)))
    if unit == "usd_split":
        a, b = str(val).split("/")
        return f"{int(round(float(a) * 100))}/{int(round(float(b) * 100))}"
    if unit == "pct":
        return str(val)
    if unit == "years":
        return str(int(val))
    if unit == "bool":
        return "true" if val in (True, "true", 1) else "false"
    return str(val)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    db_path = OUT / "peico.sqlite"
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    cur = con.cursor()

    regions = load("regions")
    lines = load("product_lines")["product_lines"]
    tiers = load("tiers")["tiers"]
    coverages = load("coverages")["coverages"]
    defaults = load("tier_coverage_defaults")["defaults"]
    elig = load("eligibility_rules")["eligibility_rules"]
    promos = load("promotions")["promotions"]
    discounts = load("discounts")["discounts"]
    kb = load("kb_documents")["kb_documents"]

    # --- regions / states ---
    for r in regions["regions"]:
        cur.execute("INSERT INTO regions VALUES (?,?,?)", (r["region"], r["label"], r.get("notes")))
    for st in regions["states"]:
        cur.execute("INSERT INTO states VALUES (?,?,?,?)",
                    (st["state"], st["region"], st["name"], st.get("notes")))

    # --- product lines ---
    for ln in lines:
        cur.execute(
            "INSERT INTO product_lines VALUES (?,?,?,?,?,?,?)",
            (ln["line"], ln["label"], ln["category"], ln.get("parent_line"),
             1 if ln.get("requires_suitability") else 0, j(ln.get("requires_underlying")),
             ln.get("notes")),
        )

    # --- tiers (+ unit lookup built alongside coverages) ---
    for line, rows in tiers.items():
        for t in rows:
            cur.execute(
                "INSERT INTO tiers VALUES (?,?,?,?,?,?,?,?)",
                (f"{line}:{t['code']}", line, t["code"], t["label"], t["position"],
                 1 if t["sellable"] else 0, s(t.get("retired_on")), t.get("notes")),
            )

    unit_of: dict[tuple[str, str], str] = {}
    for line, rows in coverages.items():
        for c in rows:
            unit_of[(line, c["code"])] = c["unit"]
            cur.execute(
                "INSERT INTO coverages VALUES (?,?,?,?,?,?,?)",
                (f"{line}:{c['code']}", line, c["code"], c["label"], c["kind"], c["unit"],
                 c.get("notes")),
            )

    # --- kb documents (before rules/promos that FK to them) ---
    for d in kb:
        cur.execute("INSERT INTO kb_documents VALUES (?,?,?,?,?)",
                    (d["doc_id"], d["title"], d["category"], j(d.get("applies_to")), d["body_md"]))

    # --- tier_coverage_defaults (money -> cents via coverage unit) ---
    for line, tier_map in defaults.items():
        for tcode, cov_map in tier_map.items():
            for ccode, cell in cov_map.items():
                unit = unit_of.get((line, ccode))
                if unit is None:
                    raise SystemExit(f"defaults reference unknown coverage {line}:{ccode}")
                cur.execute(
                    "INSERT INTO tier_coverage_defaults VALUES (?,?,?,?,?)",
                    (f"{line}:{tcode}", f"{line}:{ccode}",
                     1 if cell.get("inc") else 0,
                     canon_value(unit, cell.get("val")),
                     0 if cell.get("edit") is False else 1),
                )

    # --- promotions ---
    for p in promos:
        win = p.get("window") or {}
        cur.execute(
            "INSERT INTO promotions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (p["promo_code"], p["label"], j(p.get("scope")), s(win.get("start")), s(win.get("end")),
             j(p.get("effect")), j(p.get("stacks_with")), j(p.get("caps")),
             1 if p["active"] else 0, 1 if p["retired_rider"] else 0, p["doc_id"], p.get("notes")),
        )

    # --- discounts ---
    for d in discounts:
        cur.execute(
            "INSERT INTO discounts VALUES (?,?,?,?,?,?,?)",
            (d["discount_id"], d["code"], d["label"], j(d.get("effect")), d["stack_order"],
             d.get("eligibility"), d.get("notes")),
        )

    # --- eligibility rules ---
    for e in elig:
        line = e["line"]
        tier_id = f"{line}:{e['tier']}" if e.get("tier") else None
        cov_id = f"{line}:{e['coverage']}" if e.get("coverage") else None
        cur.execute(
            "INSERT INTO eligibility_rules VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (e["id"], line, tier_id, cov_id, e.get("state"), e["effect"], s(e.get("condition")),
             s(e.get("effective_start")), s(e.get("effective_end")), e["reason_doc"], e.get("notes")),
        )

    con.commit()
    validate(cur)
    export_json(con)
    summarize(cur)
    con.close()
    print(f"\nBuilt {db_path.relative_to(ROOT)}  (anchor {WORLD_ANCHOR_DATE})")
    return 0


def validate(cur: sqlite3.Cursor) -> None:
    print("== validator ==")
    checks = []

    def check(name, sql, want_zero=True):
        n = cur.execute(sql).fetchone()[0]
        ok = (n == 0) if want_zero else (n > 0)
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"  (count={n})"))

    # FK integrity is enforced at insert (PRAGMA foreign_keys=ON), but re-assert:
    fk = cur.execute("PRAGMA foreign_key_check").fetchall()
    checks.append(not fk)
    print(f"  [{'PASS' if not fk else 'FAIL'}] foreign keys resolve" + ("" if not fk else f"  {fk}"))

    check("retired tiers are non-sellable",
          "SELECT COUNT(*) FROM tiers WHERE retired_on IS NOT NULL AND sellable<>0")
    check("sellable tiers each have >=1 default coverage",
          "SELECT COUNT(*) FROM tiers t WHERE t.sellable=1 AND NOT EXISTS "
          "(SELECT 1 FROM tier_coverage_defaults d WHERE d.tier_id=t.tier_id)")
    check("discount stack_order is unique",
          "SELECT COUNT(*)-COUNT(DISTINCT stack_order) FROM discounts")
    check("every DENY/REQUIRE/GATE/PROHIBIT rule has a reason doc",
          "SELECT COUNT(*) FROM eligibility_rules WHERE reason_doc IS NULL")
    check("every coverage default points at an existing tier+coverage",
          "SELECT COUNT(*) FROM tier_coverage_defaults d "
          "WHERE d.tier_id NOT IN (SELECT tier_id FROM tiers) "
          "OR d.coverage_id NOT IN (SELECT coverage_id FROM coverages)")
    check("at least one retired-rider ($0 trap) promo exists",
          "SELECT COUNT(*) FROM promotions WHERE retired_rider=1", want_zero=False)

    if not all(checks):
        raise SystemExit("VALIDATION FAILED")
    print("  all checks passed")


def export_json(con: sqlite3.Connection) -> None:
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    json_cols = {"requires_underlying", "scope", "effect", "stacks_with", "caps", "applies_to"}
    out = {}
    for t in tables:
        rows = []
        for row in cur.execute(f"SELECT * FROM {t}"):
            d = dict(row)
            for k in list(d):
                if k in json_cols and isinstance(d[k], str):
                    try:
                        d[k] = json.loads(d[k])
                    except (json.JSONDecodeError, TypeError):
                        pass
            rows.append(d)
        out[t] = rows
    (OUT / "peico.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    con.row_factory = None


def summarize(cur: sqlite3.Cursor) -> None:
    print("== row counts ==")
    for t in ["regions", "states", "product_lines", "tiers", "coverages",
              "tier_coverage_defaults", "eligibility_rules", "promotions",
              "discounts", "kb_documents"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<24} {n}")


if __name__ == "__main__":
    raise SystemExit(main())
