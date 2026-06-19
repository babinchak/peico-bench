"""Render out/personas_card.md — a human-readable review of the golden personas.

  python src/peico/personas_card.py     # run after generate.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "out" / "peico.sqlite"
PERSONAS = ROOT / "data" / "personas" / "personas.yaml"
CARD = ROOT / "out" / "personas_card.md"


def main() -> None:
    covers = {p["key"]: p.get("covers", "")
              for p in yaml.safe_load(PERSONAS.read_text(encoding="utf-8"))["personas"]}
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out = ["# Golden personas — review card", "",
           "_Generated from `out/peico.sqlite`. Money in dollars (stored as cents)._", ""]

    for c in cur.execute("SELECT * FROM customers ORDER BY cust_id"):
        key = c["cust_id"].replace("CUST-", "")
        bi = cur.execute("SELECT * FROM bi_signals WHERE cust_id=?", (c["cust_id"],)).fetchone()
        legacy = c["legacy_acct"] or "—"
        if c["legacy_mismatch"]:
            legacy += " ⚠️mismatch"
        out.append(f"### {key} — {c['first_name']} {c['last_name']}")
        out.append(f"> _{covers.get(key, '')}_\n")
        out.append(f"- **{c['status']}** · {c['loyalty_tier'] or 'no loyalty'} "
                   f"({c['loyalty_points']} pts) · peico_risk **{c['peico_risk']}** · legacy {legacy}")
        if bi:
            out.append(f"- BI: churn {bi['churn_propensity_bps']/100:g}% · "
                       f"price-sens {bi['price_sensitivity_bps']/100:g}% · "
                       f"CLV ${bi['clv_cents']/100:,.0f}")

        pols = cur.execute(
            "SELECT p.policy_id, p.line, t.code tier, p.status, p.base_premium_cents b, "
            "p.final_premium_cents f, p.bundle_id, p.underlying_policy_id "
            "FROM policies p JOIN tiers t ON t.tier_id=p.tier_id WHERE p.cust_id=? ORDER BY p.policy_id",
            (c["cust_id"],)).fetchall()
        if pols:
            out.append("\n| policy | line | tier | base | final | notes |")
            out.append("|---|---|---|---|---|---|")
            for p in pols:
                notes = []
                if p["bundle_id"]:
                    notes.append(cur.execute("SELECT code FROM bundles WHERE bundle_id=?",
                                             (p["bundle_id"],)).fetchone()[0])
                if p["underlying_policy_id"]:
                    notes.append(f"↳ {p['underlying_policy_id'].split('-')[-1]}")
                su = cur.execute("SELECT outcome FROM suitability_records WHERE cust_id=? AND line=?",
                                 (c["cust_id"], p["line"])).fetchone()
                if su:
                    notes.append(f"suitability:{su['outcome']}")
                nb = cur.execute("SELECT COUNT(*) FROM beneficiaries WHERE policy_id=?",
                                 (p["policy_id"],)).fetchone()[0]
                if nb:
                    notes.append(f"{nb} beneficiaries")
                out.append(f"| {p['policy_id'].replace('POL-'+key+'-','')} | {p['line']} | {p['tier']} | "
                           f"${p['b']/100:,.0f} | ${p['f']/100:,.0f} | {', '.join(notes)} |")
        else:
            out.append("\n_(no policies — prospect)_")
        out.append("")

    CARD.write_text("\n".join(out), encoding="utf-8")
    con.close()
    print(f"Wrote {CARD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
