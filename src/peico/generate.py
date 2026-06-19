"""Generate the live world from golden personas (data/personas/personas.yaml).

  python src/peico/generate.py          # run AFTER build_reference.py

Reads the reference DB + personas, computes peico_risk, prices every policy
through the rating engine, and writes customers/objects/policies/coverages/
ledger/beneficiaries/disclosures/payments into out/peico.sqlite. Then re-prices
every policy from the DB and validates the instance layer.

Deterministic: readable ids derived from persona keys; no RNG, no wall-clock.
(The full ~5k random population is a separate later stage; this is the curated
slice for tandem agent development.)
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

import yaml


def _isodates(obj):
    """Recursively convert YAML date/datetime scalars to ISO strings."""
    if isinstance(obj, dict):
        return {k: _isodates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_isodates(v) for v in obj]
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    return obj

from rating import load_context, price  # local module (run from src/ or via sys.path)

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "out" / "peico.sqlite"
PERSONAS = ROOT / "data" / "personas" / "personas.yaml"
ENTITY_SCHEMA = Path(__file__).resolve().parent / "schema_entities.sql"
ANCHOR = "2025-06-01"
AUTO_LINES = ("AUTO", "MOTO", "RV", "BOAT", "CLSC")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _age(dob: str, as_of: str) -> int:
    y = int(as_of[:4]) - int(dob[:4])
    return y - (1 if as_of[5:] < dob[5:] else 0)


def _add_months(d: str, n: int) -> str:
    y, m, day = int(d[:4]), int(d[5:7]), d[8:10]
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}-{day}"


def compute_risk(inp: dict, state: str):
    """Deterministic peico_risk in [300,850]; credit masked (weight 0) in CA."""
    claims = inp.get("prior_claims_3yr", 0)
    late = inp.get("late_payments_12mo", 0)
    tenure = min(inp.get("tenure_years", 0), 15)
    credit = inp.get("credit_score", 700)
    masked = state == "CA"
    credit_pts = 0 if masked else round((credit - 700) * 0.4)
    score = 700 - claims * 45 - late * 25 + tenure * 4 + credit_pts
    score = max(300, min(850, int(round(score))))
    components = {
        "prior_claims": {"value": claims, "points": -claims * 45},
        "late_payments": {"value": late, "points": -late * 25},
        "tenure": {"value": inp.get("tenure_years", 0), "points": tenure * 4},
        "credit": {"value": credit, "points": credit_pts, "weight": 0 if masked else 1,
                   "masked": masked, "note": "CA: credit-based score excluded by law" if masked else None},
    }
    return score, components


def _natural(unit: str, val):
    if val is None:
        return None
    if unit in ("usd", "usd_daily"):
        return int(val) / 100
    if unit == "pct":
        return float(val)
    if unit == "years":
        return int(val)
    if unit == "bool":
        return val == "true"
    return val


def _default(con, line, tier, code):
    return con.execute(
        "SELECT d.included, d.default_value, c.unit FROM tier_coverage_defaults d "
        "JOIN coverages c ON c.coverage_id=d.coverage_id "
        "WHERE d.tier_id=? AND d.coverage_id=?", (f"{line}:{tier}", f"{line}:{code}")).fetchone()


def _natural_default(con, line, tier, code):
    row = _default(con, line, tier, code)
    if not row or not row["included"]:
        return None
    return _natural(row["unit"], row["default_value"])


def _priced_codes(payload) -> set:
    return set(payload.get("coverage_premiums", {})) | set(payload.get("rider_premiums", {}))


# --------------------------------------------------------------------------- #
# rebuild rating facts FROM the database (used by generation AND validation)
# --------------------------------------------------------------------------- #
def assemble_facts(con, policy_id: str, payloads: dict) -> dict:
    pol = con.execute("SELECT * FROM policies WHERE policy_id=?", (policy_id,)).fetchone()
    cust = con.execute("SELECT * FROM customers WHERE cust_id=?", (pol["cust_id"],)).fetchone()
    addr = con.execute("SELECT * FROM addresses WHERE address_id=?", (cust["address_id"],)).fetchone()
    line, region, state = pol["line"], addr["region"], addr["state"]
    tier = pol["tier_id"].split(":")[1]
    eff = pol["effective_date"]
    ri = json.loads(pol["rating_inputs"] or "{}")
    billing = ri.get("billing", {})
    payload = payloads[(line, region)]

    active_lines = con.execute(
        "SELECT COUNT(*) FROM policies WHERE cust_id=? AND status='ACTIVE'", (cust["cust_id"],)).fetchone()[0]
    facts = {
        "line": line, "tier": tier, "region": region, "state": state, "term_months": pol["term_months"],
        "peico_risk": cust["peico_risk"], "age": _age(cust["dob"], eff),
        "billing_plan": billing.get("plan"), "autopay": billing.get("autopay"),
        "paperless": billing.get("paperless"), "loyalty_tier": cust["loyalty_tier"],
        "status": cust["status"], "has_bundle": pol["bundle_id"] is not None,
        "active_lines": active_lines, "is_new_first_policy": cust["status"] == "PROSPECT",
        "promo_code": ri.get("promo_code"),
    }
    objs = con.execute("SELECT object_type, object_id FROM policy_objects WHERE policy_id=?", (policy_id,)).fetchall()
    veh = [con.execute("SELECT * FROM vehicles WHERE vehicle_id=?", (o["object_id"],)).fetchone()
           for o in objs if o["object_type"] == "vehicle"]
    dwl = [con.execute("SELECT * FROM dwellings WHERE dwelling_id=?", (o["object_id"],)).fetchone()
           for o in objs if o["object_type"] == "dwelling"]
    pet = [con.execute("SELECT * FROM pets WHERE pet_id=?", (o["object_id"],)).fetchone()
           for o in objs if o["object_type"] == "pet"]

    pcs = [r["coverage_id"].split(":")[1]
           for r in con.execute("SELECT coverage_id FROM policy_coverages WHERE policy_id=?", (policy_id,))]
    facts["coverages"] = [c for c in pcs if c in _priced_codes(payload)]

    if line in AUTO_LINES and veh:
        v = veh[0]
        facts.update(driver_age=facts["age"], annual_miles=v["annual_miles"],
                     vehicle_age=int(eff[:4]) - v["year"], incidents_5yr=ri.get("incidents_5yr", 0),
                     exposure_count=len(veh))
    elif line in ("HOME", "CONDO") and dwl:
        d = dwl[0]
        facts.update(replacement_cost=d["replacement_cost_cents"] / 100, roof_age=d["roof_age"],
                     construction=d["construction"], protection_class=d["protection_class"],
                     dist_to_coast_mi=d["dist_to_coast_mi"])
        whd = _natural_default(con, line, tier, "WIND_HAIL")
        if whd is not None:
            facts["wind_hail_deductible"] = whd
    elif line == "RENT":
        facts["contents"] = _natural_default(con, line, tier, "CONTENTS")
    elif line == "UMBR":
        facts["underlying_units"] = con.execute(
            "SELECT COUNT(*) FROM policies WHERE cust_id=? AND status='ACTIVE' AND line IN ('AUTO','HOME')",
            (cust["cust_id"],)).fetchone()[0]
    elif line == "PET" and pet:
        facts.update(species=pet[0]["species"], pet_age=pet[0]["age"], exposure_count=len(pet),
                     reimburse_pct=_natural_default(con, line, tier, "REIMB_PCT"))
    elif line in ("LIFE_T", "LIFE_W"):
        facts.update(face=_natural_default(con, line, tier, "FACE"), smoker=ri.get("smoker", False))
        if line == "LIFE_T":
            facts["term_len"] = _natural_default(con, line, tier, "TERM_LEN")
    return facts


# --------------------------------------------------------------------------- #
# generation
# --------------------------------------------------------------------------- #
def generate(con, ctx, payloads):
    personas = _isodates(yaml.safe_load(PERSONAS.read_text(encoding="utf-8")))["personas"]
    for p in personas:
        key = p["key"]
        state = p["address"]["state"]
        region = con.execute("SELECT region FROM states WHERE state=?", (state,)).fetchone()[0]
        addr_id = f"ADDR-{key}"
        a = p["address"]
        con.execute("INSERT INTO addresses VALUES (?,?,?,?,?,?)",
                    (addr_id, a["line1"], a["city"], state, a["zip"], region))

        peico_risk, components = compute_risk(p.get("risk_inputs", {}), state)
        cust_id = f"CUST-{key}"
        con.execute(
            "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cust_id, p.get("legacy_acct"), 1 if p.get("legacy_mismatch") else 0, p["status"],
             p["first_name"], p["last_name"], p["dob"],
             f"{p['first_name'].lower()}.{p['last_name'].lower()}@example.com", None, addr_id,
             peico_risk, json.dumps(components), p.get("tenure_start"), p.get("loyalty_tier"),
             0, ANCHOR))

        bi = p.get("bi", {})
        con.execute("INSERT INTO bi_signals VALUES (?,?,?,?,?,?,?)",
                    (cust_id, int(bi.get("churn", 0) * 10000), int(bi.get("upsell", 0) * 10000),
                     int(bi.get("price_sensitivity", 0) * 10000), int(bi.get("clv", 0) * 100),
                     1 if bi.get("fraud") else 0, bi.get("contactability")))

        # objects + ref -> (type, id) map
        ref = {}
        for m in p.get("members", []):
            mid = f"MBR-{key}-{m['ref']}"
            con.execute("INSERT INTO household_members VALUES (?,?,?,?,?,?,?,?,?)",
                        (mid, cust_id, m["role"], m.get("first_name"), m.get("last_name"), m.get("dob"),
                         m.get("license_status"), m.get("years_licensed"), m.get("incidents_5yr", 0)))
        for v in p.get("vehicles", []):
            vid = f"VEH-{key}-{v['ref']}"
            ref[v["ref"]] = ("vehicle", vid)
            con.execute("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (vid, cust_id, v["year"], v.get("make"), v.get("model"),
                         f"VINFAKE{key[:3].upper()}{v['ref']}", v.get("usage"), v.get("annual_miles"),
                         1 if v.get("financed") else 0, addr_id))
        for d in p.get("dwellings", []):
            did = f"DWL-{key}-{d['ref']}"
            ref[d["ref"]] = ("dwelling", did)
            con.execute("INSERT INTO dwellings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (did, cust_id, d.get("type"), d.get("year_built"), d.get("construction"),
                         d.get("roof_age"), d.get("sq_ft"), int(d["replacement_cost"] * 100),
                         d.get("protection_class"), d.get("dist_to_coast_mi"),
                         int(d["hoa_master_deductible"] * 100) if d.get("hoa_master_deductible") else None))
        for pet in p.get("pets", []):
            pid = f"PET-{key}-{pet['ref']}"
            ref[pet["ref"]] = ("pet", pid)
            con.execute("INSERT INTO pets VALUES (?,?,?,?,?,?)",
                        (pid, cust_id, pet.get("name"), pet.get("species"), pet.get("breed"), pet.get("age")))

        # bundle (before policies so policies can point at it)
        bundle_id = None
        if p.get("bundle"):
            bundle_id = f"BND-{key}"
            con.execute("INSERT INTO bundles VALUES (?,?,?,?,?)",
                        (bundle_id, cust_id, p["bundle"]["code"], "DISC-MULTILINE", ANCHOR))

        # policies — insert, then assemble facts from DB, price, update
        for pol in p.get("policies", []):
            pid = f"POL-{key}-{pol['ref']}"
            tier_id = f"{pol['line']}:{pol['tier']}"
            in_bundle = bundle_id if (p.get("bundle") and pol["ref"] in p["bundle"]["members"]) else None
            underlying = f"POL-{key}-{pol['underlying']}" if pol.get("underlying") else None
            rating_inputs = {"billing": pol.get("billing", {}), "incidents_5yr": pol.get("incidents_5yr", 0),
                             "smoker": pol.get("smoker", False), "promo_code": pol.get("promo")}
            con.execute(
                "INSERT INTO policies (policy_id,cust_id,line,tier_id,status,effective_date,"
                "expiration_date,term_months,rating_as_of,rating_inputs,underlying_policy_id,"
                "bundle_id,rep_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, cust_id, pol["line"], tier_id, "ACTIVE", pol["effective"],
                 _add_months(pol["effective"], pol["term_months"]), pol["term_months"], pol["effective"],
                 json.dumps(rating_inputs), underlying, in_bundle, pol.get("rep"), ANCHOR))

            for o in pol.get("objects", []):
                otype, oid = ref[o]
                con.execute("INSERT INTO policy_objects VALUES (?,?,?)", (pid, otype, oid))

            # coverage instances: included tier defaults + persona extras
            included = con.execute(
                "SELECT coverage_id, default_value FROM tier_coverage_defaults "
                "WHERE tier_id=? AND included=1", (tier_id,)).fetchall()
            present = set()
            for c in included:
                con.execute("INSERT INTO policy_coverages VALUES (?,?,?,?)",
                            (pid, c["coverage_id"], c["default_value"], None))
                present.add(c["coverage_id"])
            for code in pol.get("coverages_extra", []):
                cid = f"{pol['line']}:{code}"
                if cid not in present:
                    con.execute("INSERT INTO policy_coverages VALUES (?,?,?,?)", (pid, cid, "true", None))

            facts = assemble_facts(con, pid, payloads)
            res = price(facts, pol["effective"], ctx)
            con.execute("UPDATE policies SET base_premium_cents=?, final_premium_cents=?, "
                        "premium_breakdown=? WHERE policy_id=?",
                        (res["base_premium_cents"], res["final_premium_cents"],
                         json.dumps(res["breakdown"]), pid))
            cov_amt = {e["code"]: e["amount_cents"] for e in res["breakdown"] if e["step"] == "COVERAGE"}
            for code, amt in cov_amt.items():
                con.execute("UPDATE policy_coverages SET premium_contribution_cents=? "
                            "WHERE policy_id=? AND coverage_id=?", (amt, pid, f"{pol['line']}:{code}"))

            # suitability (life/health)
            if pol.get("suitability"):
                su = pol["suitability"]
                con.execute("INSERT INTO suitability_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (f"SUIT-{pid}", cust_id, pol["line"], int(su["income"] * 100),
                             su.get("dependents", 0), int(su.get("existing_coverage", 0) * 100),
                             su.get("stated_need"), su.get("horizon"), su.get("risk_tolerance"),
                             pol["effective"], su["outcome"]))
            # beneficiaries
            for i, b in enumerate(pol.get("beneficiaries", [])):
                con.execute("INSERT INTO beneficiaries VALUES (?,?,?,?,?,?,?,?)",
                            (f"BEN-{pid}-{i}", pid, cust_id, b["name"], b.get("relationship"),
                             b["kind"], b["pct"], pol["effective"]))
            # disclosure deliveries (mandatory, line + optional state scope)
            for dr in con.execute(
                    "SELECT disclosure_id, code, state FROM required_disclosures "
                    "WHERE line=? AND mandatory=1", (pol["line"],)):
                if dr["state"] and dr["state"] != state:
                    continue
                con.execute("INSERT INTO disclosure_deliveries VALUES (?,?,?,?,?,?,?)",
                            (f"DLV-{pid}-{dr['code']}", pid, dr["disclosure_id"], pol["effective"],
                             "ESIGN", 1, None))
            # payments
            final = res["final_premium_cents"]
            plan = (pol.get("billing") or {}).get("plan", "PAY_IN_FULL")
            late = p.get("risk_inputs", {}).get("late_payments_12mo", 0) > 0
            if plan == "PAY_IN_FULL":
                con.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?)",
                            (f"PMT-{pid}-0", cust_id, pid, pol["effective"], pol["effective"], final,
                             "LATE" if late else "PAID"))
            else:
                monthly = round(final / pol["term_months"])
                con.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?)",
                            (f"PMT-{pid}-0", cust_id, pid, pol["effective"], pol["effective"], monthly,
                             "LATE" if late else "PAID"))
                nxt = _add_months(pol["effective"], 1)
                con.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?)",
                            (f"PMT-{pid}-1", cust_id, pid, nxt, None, monthly, "SCHEDULED"))

        # loyalty ledger + points cache
        ledger = p.get("ledger")
        if ledger:
            for i, e in enumerate(ledger):
                con.execute("INSERT INTO loyalty_ledger VALUES (?,?,?,?,?,?,?)",
                            (f"LL-{key}-{i}", cust_id, e["ts"], e["delta"], e.get("reason"),
                             e.get("expires_on"), None))
            pts = sum(e["delta"] for e in ledger)
        elif p.get("loyalty_points"):
            pts = p["loyalty_points"]
            con.execute("INSERT INTO loyalty_ledger VALUES (?,?,?,?,?,?,?)",
                        (f"LL-{key}-0", cust_id, p.get("tenure_start", ANCHOR), pts, "PREMIUM_EARN",
                         None, None))
        else:
            pts = 0
        con.execute("UPDATE customers SET loyalty_points=? WHERE cust_id=?", (pts, cust_id))


# --------------------------------------------------------------------------- #
# instance validation
# --------------------------------------------------------------------------- #
def validate(con, ctx, payloads) -> None:
    print("== instance validator ==")
    checks = []

    def ok(name, cond, extra=""):
        checks.append(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond else f"  {extra}"))

    # premiums recompute from DB facts
    bad = []
    for r in con.execute("SELECT policy_id, base_premium_cents, final_premium_cents, rating_as_of FROM policies"):
        res = price(assemble_facts(con, r["policy_id"], payloads), r["rating_as_of"], ctx)
        if (res["base_premium_cents"], res["final_premium_cents"]) != (r["base_premium_cents"], r["final_premium_cents"]):
            bad.append(r["policy_id"])
    ok("every policy premium recomputes from DB facts", not bad, bad)

    loyalty = con.execute(
        "SELECT c.cust_id FROM customers c WHERE c.loyalty_points <> "
        "COALESCE((SELECT SUM(delta_points) FROM loyalty_ledger l WHERE l.cust_id=c.cust_id),0)").fetchall()
    ok("loyalty_points cache == ledger sum", not loyalty, [r[0] for r in loyalty])

    bundles = con.execute(
        "SELECT b.bundle_id FROM bundles b WHERE (SELECT COUNT(*) FROM policies p "
        "WHERE p.bundle_id=b.bundle_id AND p.status='ACTIVE') < 2").fetchall()
    ok("every bundle has >=2 active members", not bundles, [r[0] for r in bundles])

    umbr = con.execute(
        "SELECT p.policy_id FROM policies p WHERE p.line='UMBR' AND p.status='ACTIVE' AND NOT EXISTS "
        "(SELECT 1 FROM policies u WHERE u.policy_id=p.underlying_policy_id AND u.status='ACTIVE' "
        "AND u.line IN ('AUTO','HOME') AND u.cust_id=p.cust_id)").fetchall()
    ok("every umbrella has an in-force underlying auto/home", not umbr, [r[0] for r in umbr])

    ben = con.execute(
        "SELECT policy_id FROM beneficiaries WHERE kind='PRIMARY' GROUP BY policy_id "
        "HAVING SUM(percentage) <> 100").fetchall()
    ok("primary beneficiary splits sum to 100", not ben, [r[0] for r in ben])

    suit = con.execute(
        "SELECT p.policy_id FROM policies p WHERE p.line IN ('LIFE_T','LIFE_W','HLTH') "
        "AND p.status='ACTIVE' AND NOT EXISTS "
        "(SELECT 1 FROM suitability_records s WHERE s.cust_id=p.cust_id AND s.line=p.line)").fetchall()
    ok("every active life/health policy has a suitability record", not suit, [r[0] for r in suit])

    disc = con.execute(
        "SELECT p.policy_id, d.code FROM policies p JOIN required_disclosures d ON d.line=p.line "
        "JOIN customers c ON c.cust_id=p.cust_id JOIN addresses a ON a.address_id=c.address_id "
        "WHERE p.status='ACTIVE' AND d.mandatory=1 AND (d.state IS NULL OR d.state=a.state) "
        "AND NOT EXISTS (SELECT 1 FROM disclosure_deliveries v "
        "WHERE v.policy_id=p.policy_id AND v.disclosure_id=d.disclosure_id)").fetchall()
    ok("every active policy delivered its mandatory disclosures", not disc, [tuple(r) for r in disc])

    if not all(checks):
        raise SystemExit("INSTANCE VALIDATION FAILED")
    print("  all instance checks passed")


def summarize(con) -> None:
    print("== instance counts ==")
    for t in ["customers", "addresses", "household_members", "vehicles", "dwellings", "pets",
              "policies", "policy_coverages", "policy_objects", "suitability_records", "bundles",
              "loyalty_ledger", "beneficiaries", "disclosure_deliveries", "payments", "bi_signals"]:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<22} {n}")
    print("== priced policies ==")
    for r in con.execute(
            "SELECT p.policy_id, p.line, t.code tier, c.status, "
            "p.base_premium_cents b, p.final_premium_cents f "
            "FROM policies p JOIN tiers t ON t.tier_id=p.tier_id "
            "JOIN customers c ON c.cust_id=p.cust_id ORDER BY p.policy_id"):
        print(f"  {r['policy_id']:<26} {r['line']:<6} {r['tier']:<10} "
              f"base ${r['b']/100:>9,.2f}  final ${r['f']/100:>9,.2f}")


def main() -> int:
    if not DB.exists():
        raise SystemExit("run build_reference.py first (out/peico.sqlite missing)")
    ctx = load_context(DB)
    payloads = {k: rows[0]["payload"] for k, rows in ctx.rate_tables.items()}

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(ENTITY_SCHEMA.read_text(encoding="utf-8"))
    con.execute("DELETE FROM disclosure_deliveries")
    con.execute("DELETE FROM beneficiaries")
    generate(con, ctx, payloads)
    con.commit()
    validate(con, ctx, payloads)
    summarize(con)
    con.close()
    print(f"\nGenerated golden personas into {DB.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
