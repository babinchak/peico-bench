"""Render out/data_card.md — a human-readable review of the reference DB.

  python src/peico/review_card.py

Converts stored cents back to dollars for display. This is the artifact to eyeball
when reviewing whether the product definitions are right.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "out" / "peico.sqlite"
CARD = ROOT / "out" / "data_card.md"


def money(cents: str) -> str:
    d = int(cents) / 100
    return f"${d:,.0f}" if d == int(d) else f"${d:,.2f}"


def fmt_value(unit: str, val) -> str:
    if val is None:
        return "✓ derived"
    if unit in ("usd", "usd_daily"):
        out = money(val)
        return out + "/day" if unit == "usd_daily" else out
    if unit == "usd_split":
        a, b = val.split("/")
        return f"{money(a)}/{money(b)}"
    if unit == "pct":
        return f"{float(val) * 100:g}%"
    if unit == "years":
        return f"{val}yr"
    if unit == "bool":
        return "✓" if val == "true" else "—"
    return str(val)


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    out: list[str] = ["# PEICO reference data — review card", ""]
    out.append("_Generated from `out/peico.sqlite`. Money shown in dollars (stored as cents)._\n")

    # counts
    out.append("## Row counts\n")
    for t in ["regions", "states", "product_lines", "tiers", "coverages",
              "tier_coverage_defaults", "eligibility_rules", "promotions",
              "discounts", "kb_documents"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out.append(f"- **{t}**: {n}")
    out.append("")

    # per-line product matrices
    out.append("## Product lines → tier × coverage matrices\n")
    lines = cur.execute("SELECT * FROM product_lines ORDER BY category, line").fetchall()
    for ln in lines:
        line = ln["line"]
        flags = []
        if ln["requires_suitability"]:
            flags.append("suitability required")
        if ln["requires_underlying"]:
            flags.append(f"requires underlying {ln['requires_underlying']}")
        if ln["parent_line"]:
            flags.append(f"sub-line of {ln['parent_line']}")
        suffix = f" — _{'; '.join(flags)}_" if flags else ""
        out.append(f"### {line} — {ln['label']}{suffix}")
        if ln["notes"]:
            out.append(f"> {ln['notes']}\n")

        tiers = cur.execute(
            "SELECT * FROM tiers WHERE line=? ORDER BY position", (line,)).fetchall()
        covs = cur.execute(
            "SELECT * FROM coverages WHERE line=? ORDER BY rowid", (line,)).fetchall()
        unit = {c["coverage_id"]: c["unit"] for c in covs}

        # header
        tlabels = []
        for t in tiers:
            lab = t["code"]
            if not t["sellable"]:
                lab += " ⛔"  # retired / non-sellable
            tlabels.append(lab)
        out.append("| coverage | kind | " + " | ".join(tlabels) + " |")
        out.append("|---|---|" + "---|" * len(tiers))

        defaults = {}
        for d in cur.execute(
                "SELECT * FROM tier_coverage_defaults WHERE tier_id LIKE ?", (f"{line}:%",)):
            defaults[(d["tier_id"], d["coverage_id"])] = d

        for c in covs:
            row = [f"`{c['code']}`", c["kind"]]
            for t in tiers:
                d = defaults.get((t["tier_id"], c["coverage_id"]))
                if d is None or not d["included"]:
                    row.append("—")
                else:
                    row.append(fmt_value(unit[c["coverage_id"]], d["default_value"]))
            out.append("| " + " | ".join(row) + " |")
        # retired-tier notes
        for t in tiers:
            if not t["sellable"] and t["notes"]:
                out.append(f"\n> ⛔ **{t['code']}** (retired {t['retired_on']}): {t['notes']}")
        out.append("")

    # eligibility rules
    out.append("## Eligibility & rating rules\n")
    out.append("| rule | line | scope | effect | condition | doc |")
    out.append("|---|---|---|---|---|---|")
    for e in cur.execute("SELECT * FROM eligibility_rules ORDER BY rule_id"):
        scope = " ".join(filter(None, [
            e["tier_id"] and e["tier_id"].split(":")[1],
            e["coverage_id"] and e["coverage_id"].split(":")[1],
            e["state"] and f"@{e['state']}"])) or "—"
        out.append(f"| {e['rule_id']} | {e['line']} | {scope} | {e['effect']} | "
                   f"{e['condition'] or '—'} | `{e['reason_doc']}` |")
    out.append("")

    # promotions
    out.append("## Promotions\n")
    out.append("| code | window | effect | active | $0 trap | notes |")
    out.append("|---|---|---|---|---|---|")
    for p in cur.execute("SELECT * FROM promotions ORDER BY promo_code"):
        out.append(f"| {p['promo_code']} | {p['window_start']}→{p['window_end']} | "
                   f"{p['effect']} | {'yes' if p['active'] else 'no'} | "
                   f"{'⚠️ yes' if p['retired_rider'] else 'no'} | {p['notes'] or ''} |")
    out.append("")

    # discounts
    out.append("## Discounts (canonical stack order)\n")
    out.append("| order | code | effect | eligibility |")
    out.append("|---|---|---|---|")
    for d in cur.execute("SELECT * FROM discounts ORDER BY stack_order"):
        out.append(f"| {d['stack_order']} | {d['code']} | {d['effect']} | {d['eligibility']} |")
    out.append("")

    CARD.write_text("\n".join(out), encoding="utf-8")
    con.close()
    print(f"Wrote {CARD.relative_to(ROOT)} ({len(out)} lines)")


if __name__ == "__main__":
    main()
