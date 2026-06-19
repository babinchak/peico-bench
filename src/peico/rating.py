"""PEICO rating engine — deterministic, pure pricing.

Implements docs/03-rating-engine.md: price(facts, as_of) -> base/final premium +
an ordered breakdown that reconciles step by step. Pure (no wall-clock, no RNG);
as_of is an explicit argument. Integer cents throughout, round-half-up at each
multiplicative step.

Single source of truth: imported by the generator (to fill final_premium_cents)
and the validator (to re-verify it). Reference inputs are read from out/peico.sqlite
via load_context(); pricing itself never touches the DB.

Demo:
  python src/peico/rating.py        # prices a few example policies, prints breakdowns
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "out" / "peico.sqlite"

# Engine-level fees (placeholders until a state_fees reference table exists).
POLICY_FEE_CENTS = 2500          # flat per-term policy fee
INSTALLMENT_FEE_CENTS = 3600     # fractional-pay surcharge when not paid in full

# factor-curve key -> facts key (when they differ)
FACTOR_INPUT = {"risk_score": "peico_risk", "contents_per_1000": "contents"}


# --------------------------------------------------------------------------- #
# money helpers
# --------------------------------------------------------------------------- #
def _r(x) -> int:
    """Round to integer cents, half-up."""
    return int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _mul(cents: int, factor) -> int:
    return _r(Decimal(cents) * Decimal(str(factor)))


def _to_cents(dollars) -> int:
    return _r(Decimal(str(dollars)) * 100)


def _curve(curve, value):
    """Factor lookup: list[{max,f}] (first bucket value<=max wins) or {key:f} map."""
    if isinstance(curve, dict):
        for k in (str(value), f"{value:.2f}" if isinstance(value, (int, float)) else None):
            if k is not None and k in curve:
                return curve[k]
        return 1.0
    for bucket in curve:
        if value <= bucket["max"]:
            return bucket["f"]
    return curve[-1]["f"]


# --------------------------------------------------------------------------- #
# context (reference snapshot)
# --------------------------------------------------------------------------- #
@dataclass
class Context:
    rate_tables: dict = field(default_factory=dict)   # (line,region) -> [rows]
    discounts: list = field(default_factory=list)     # sorted by stack_order
    promotions: dict = field(default_factory=dict)    # promo_code -> row


def load_context(db_path: Path = DB) -> Context:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    ctx = Context()
    for r in cur.execute("SELECT * FROM rate_tables"):
        ctx.rate_tables.setdefault((r["line"], r["region"]), []).append({
            "effective_start": r["effective_start"], "effective_end": r["effective_end"],
            "payload": json.loads(r["payload"]),
        })
    for d in cur.execute("SELECT * FROM discounts ORDER BY stack_order"):
        ctx.discounts.append({
            "code": d["code"], "stack_order": d["stack_order"], "effect": json.loads(d["effect"])})
    for p in cur.execute("SELECT * FROM promotions"):
        ctx.promotions[p["promo_code"]] = {
            "scope": json.loads(p["scope"]) if p["scope"] else {},
            "window_start": p["window_start"], "window_end": p["window_end"],
            "effect": json.loads(p["effect"]) if p["effect"] else {},
            "caps": json.loads(p["caps"]) if p["caps"] else {},
            "active": p["active"], "retired_rider": p["retired_rider"],
        }
    con.close()
    return ctx


def _select_rate_table(ctx: Context, line: str, region: str, as_of: str):
    rows = ctx.rate_tables.get((line, region), [])
    for row in rows:
        if row["effective_start"] <= as_of < row["effective_end"]:
            return row["payload"]
    raise ValueError(f"no rate_table for {line}/{region} effective {as_of}")


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #
def price(facts: dict, as_of: str, ctx: Context) -> dict:
    """Price one policy. `facts` keys are documented in build_demo_facts()."""
    line, region, tier = facts["line"], facts["region"], facts["tier"]
    payload = _select_rate_table(ctx, line, region, as_of)
    bd: list[dict] = []
    state = facts.get("state")

    def step(name, code, detail, running, factor=None, amount=None):
        bd.append({"step": name, "code": code, "detail": detail, "factor": factor,
                   "amount_cents": amount, "running_cents": running})

    # 1. BASE -------------------------------------------------------------- #
    if "base_rate" in payload:
        base = _to_cents(payload["base_rate"])
        base_detail = f"base_rate ${payload['base_rate']}"
    elif "rate_per_1000" in payload:
        base = _r(Decimal(str(payload["rate_per_1000"])) * Decimal(str(facts["replacement_cost"])) / 1000 * 100)
        base_detail = f"${payload['rate_per_1000']}/$1k × RC ${facts['replacement_cost']:,}"
    elif "rate_per_1000_by_age" in payload:
        rate = _curve(payload["rate_per_1000_by_age"], facts["age"])
        base = _r(Decimal(str(rate)) * Decimal(str(facts["face"])) / 1000 * 100)
        base_detail = f"${rate}/$1k @age{facts['age']} × face ${facts['face']:,}"
    elif "rate_pct_of_trip_cost" in payload:
        base = _to_cents(Decimal(str(payload["rate_pct_of_trip_cost"])) * Decimal(str(facts["trip_cost"])))
        base_detail = f"{payload['rate_pct_of_trip_cost']} × trip ${facts['trip_cost']:,}"
    else:
        raise ValueError(f"rate_table for {line} has no recognized base form")
    running = base
    step("BASE", "base", base_detail, running)

    tf = payload.get("tier_factors", {}).get(tier, 1.0)
    running = _mul(running, tf)
    step("BASE", f"tier:{tier}", f"tier factor ×{tf}", running, factor=tf)

    if "term_factors" in payload:  # life: level-term length affects rate
        tlf = payload["term_factors"].get(str(facts.get("term_len", 20)), 1.0)
        running = _mul(running, tlf)
        step("BASE", "term_len", f"{facts.get('term_len')}yr term ×{tlf}", running, factor=tlf)
    if payload.get("smoker_factor") and facts.get("smoker"):
        sf = payload["smoker_factor"]
        running = _mul(running, sf)
        step("BASE", "smoker", f"smoker ×{sf}", running, factor=sf)

    rf = payload.get("region_factor", 1.0)
    running = _mul(running, rf)
    step("BASE", f"region:{region}", f"region factor ×{rf}", running, factor=rf)

    term_months = facts.get("term_months", 12)
    if term_months != 12 and "rate_pct_of_trip_cost" not in payload and "rate_per_1000_by_age" not in payload:
        prorate = Decimal(term_months) / 12
        running = _mul(running, prorate)
        step("BASE", "term", f"{term_months}mo proration ×{prorate}", running, factor=float(prorate))

    # 2. EXPOSURE ---------------------------------------------------------- #
    count = facts.get("exposure_count", 1)
    if payload.get("unit") in ("per_vehicle", "per_pet") and count != 1:
        running = running * count
        step("EXPOSURE", "count", f"× {count} {payload['unit'].split('_')[1]}s", running, factor=count)

    # 3. RISK FACTORS (+ state masking) ----------------------------------- #
    prohibited = set(payload.get("prohibited_factors_by_state", {}).get(state, []))
    for key, curve in payload.get("factors", {}).items():
        if key in prohibited:
            step("RISK", f"factor:{key}", "excluded due to state law", running, factor=1.0)
            continue
        fval = facts.get(FACTOR_INPUT.get(key, key))
        if fval is None:
            continue
        f = _curve(curve, fval)
        running = _mul(running, f)
        step("RISK", f"factor:{key}", f"{key}={fval} ×{f}", running, factor=f)
    if "wind_hail_deductible_credit" in payload and facts.get("wind_hail_deductible") is not None:
        whc = _curve(payload["wind_hail_deductible_credit"], facts["wind_hail_deductible"])
        running = _mul(running, whc)
        step("RISK", "wind_hail_ded", f"wind/hail ded {facts['wind_hail_deductible']} ×{whc}", running, factor=whc)

    # 4. COVERAGE (priced optional components / riders) ------------------- #
    prem_map = {**payload.get("coverage_premiums", {}), **payload.get("rider_premiums", {})}
    for cov in facts.get("coverages", []):
        if cov in prem_map and prem_map[cov]:
            amt = _to_cents(prem_map[cov])
            if term_months != 12 and "rate_per_1000_by_age" not in payload:
                amt = _mul(amt, Decimal(term_months) / 12)
            running += amt
            step("COVERAGE", cov, f"+ {cov} ${prem_map[cov]}", running, amount=amt)

    # 5. FEES / TAXES ------------------------------------------------------ #
    running += POLICY_FEE_CENTS
    step("FEES", "policy_fee", "+ policy fee", running, amount=POLICY_FEE_CENTS)
    if facts.get("billing_plan") and facts["billing_plan"] != "PAY_IN_FULL":
        running += INSTALLMENT_FEE_CENTS
        step("FEES", "installment", "+ fractional-pay surcharge", running, amount=INSTALLMENT_FEE_CENTS)
    base_premium_cents = running

    # 6. DISCOUNTS (multiplicative/additive in stack_order) --------------- #
    for d in ctx.discounts:
        if not _discount_eligible(d["code"], facts):
            continue
        eff = d["effect"]
        if eff["type"] == "PCT_OFF":
            running = _mul(running, 1 - eff["value"])
            step("DISCOUNT", d["code"], f"−{eff['value']*100:g}%", running, factor=1 - eff["value"])
        else:  # DOLLARS_OFF
            amt = _to_cents(eff["value"])
            running -= amt
            step("DISCOUNT", d["code"], f"−${eff['value']}", running, amount=-amt)

    # 7. PROMOS ------------------------------------------------------------ #
    floor_cents = 0
    promo_code = facts.get("promo_code")
    if promo_code and promo_code in ctx.promotions:
        running, floor_cents = _apply_promo(running, promo_code, ctx.promotions[promo_code],
                                            facts, as_of, step)

    # 8. FLOORS / CAPS ----------------------------------------------------- #
    if floor_cents and running < floor_cents:
        step("FLOOR", "min_premium", f"raise to floor ${floor_cents/100:.0f}", floor_cents)
        running = floor_cents

    return {"base_premium_cents": base_premium_cents, "final_premium_cents": running,
            "breakdown": bd}


def _discount_eligible(code: str, facts: dict) -> bool:
    if code == "SAFE_DRIVER":
        return facts.get("line") in ("AUTO", "MOTO") and facts.get("incidents_5yr", 0) == 0
    if code == "MULTILINE":
        return bool(facts.get("has_bundle"))
    if code == "PAID_IN_FULL":
        return facts.get("billing_plan") == "PAY_IN_FULL"
    if code == "PAPERLESS":
        return bool(facts.get("paperless"))
    if code == "AUTOPAY":
        return bool(facts.get("autopay"))
    if code == "LOYALTY":
        return facts.get("loyalty_tier") in ("Timber", "OldGrowth")
    return False


def _promo_in_scope(scope: dict, facts: dict) -> bool:
    lines = scope.get("lines", "ALL")
    if lines != "ALL" and facts["line"] not in lines:
        return False
    regions = scope.get("regions", "ALL")
    if regions != "ALL" and facts["region"] not in regions:
        return False
    cust = scope.get("customer", "ANY")
    if cust == "NEW_FIRST_POLICY" and not facts.get("is_new_first_policy"):
        return False
    if cust == "EXISTING" and facts.get("status") != "CUSTOMER":
        return False
    if cust == "NEW" and facts.get("status") != "PROSPECT":
        return False
    need = scope.get("requires_active_lines")
    if need and facts.get("active_lines", 0) < need:
        return False
    return True


def _apply_promo(running, code, promo, facts, as_of, step):
    # Activity is decided by the WINDOW vs as_of (pure/deterministic). The static
    # promotions.active flag is a website "active right now" hint, not used here.
    if not (promo["window_start"] <= as_of < promo["window_end"]):
        step("PROMO", code, "outside window for as_of — no effect", running, amount=0)
        return running, 0
    if not _promo_in_scope(promo["scope"], facts):
        step("PROMO", code, "out of scope — no effect", running, amount=0)
        return running, 0
    caps = promo["caps"]
    if promo["retired_rider"]:
        step("PROMO", code, "retired rider — $0 benefit (trap)", running, amount=0)
        return running, _to_cents(caps.get("min_premium_floor_usd", 0))

    eff = promo["effect"]
    benefit = _mul(running, eff["value"]) if eff["type"] == "PCT_OFF" else _to_cents(eff["value"])
    cap = caps.get("max_benefit_usd")
    if cap is not None:
        benefit = min(benefit, _to_cents(cap))
    running -= benefit
    detail = (f"−{eff['value']*100:g}%" if eff["type"] == "PCT_OFF" else f"−${eff['value']}")
    if cap is not None:
        detail += f" (cap ${cap})"
    step("PROMO", code, detail, running, amount=-benefit)
    return running, _to_cents(caps.get("min_premium_floor_usd", 0))


# --------------------------------------------------------------------------- #
# demo / smoke test
# --------------------------------------------------------------------------- #
def _print_breakdown(title, facts, as_of, res):
    print(f"\n### {title}   (as_of {as_of})")
    print(f"{'step':<10}{'code':<22}{'detail':<42}{'running':>12}")
    print("-" * 86)
    for e in res["breakdown"]:
        print(f"{e['step']:<10}{e['code']:<22}{e['detail']:<42}${e['running_cents']/100:>10,.2f}")
    print(f"{'':<74}base  ${res['base_premium_cents']/100:>9,.2f}")
    print(f"{'':<74}FINAL ${res['final_premium_cents']/100:>9,.2f}")


def _reconcile(res) -> bool:
    """Assert each running total follows from the previous via factor/amount."""
    prev = None
    for e in res["breakdown"]:
        if prev is not None and e["factor"] is not None:
            exp = _mul(prev, e["factor"])
            if exp != e["running_cents"] and e["step"] != "EXPOSURE":
                return False
        if prev is not None and e["amount_cents"] is not None and e["step"] != "FLOOR":
            if prev + e["amount_cents"] != e["running_cents"]:
                return False
        prev = e["running_cents"]
    return True


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # breakdowns use ×/− glyphs
    except (AttributeError, ValueError):
        pass
    ctx = load_context()

    auto = {
        "line": "AUTO", "tier": "PINE", "region": "R-MW", "state": "IL", "term_months": 12,
        "peico_risk": 720, "driver_age": 40, "annual_miles": 12000, "vehicle_age": 4,
        "incidents_5yr": 0, "coverages": ["GAP"], "billing_plan": "PAY_IN_FULL",
        "has_bundle": True, "loyalty_tier": "Timber", "paperless": True, "autopay": True,
        "status": "CUSTOMER", "active_lines": 2, "promo_code": "PINEBUNDLE",
    }
    home_fl = {
        "line": "HOME", "tier": "EVERGREEN", "region": "R-SE", "state": "FL", "term_months": 12,
        "replacement_cost": 400000, "peico_risk": 690, "roof_age": 12, "construction": "MASONRY",
        "protection_class": 4, "dist_to_coast_mi": 3, "wind_hail_deductible": 0.02,
        "coverages": ["WATER_BACK"], "billing_plan": "INSTALLMENTS", "promo_code": "COASTALSHIELD",
    }
    life = {
        "line": "LIFE_W", "tier": "EVERGREEN", "region": "R-W", "state": "CA",
        "age": 45, "face": 100000, "smoker": False, "coverages": ["WAIVER"],
        "billing_plan": "PAY_IN_FULL",
    }
    ca_auto = {**auto, "region": "R-W", "state": "CA", "promo_code": None,
               "has_bundle": False, "loyalty_tier": None}

    cases = [
        ("AUTO PINE / Midwest — bundle + loyalty + PINEBUNDLE promo", auto, "2026-03-01"),
        ("HOME EVERGREEN / Florida — hurricane + coastal promo", home_fl, "2025-09-01"),
        ("LIFE_W EVERGREEN / California — age-rated, region-invariant", life, "2026-03-01"),
        ("AUTO PINE / California — same risk, CA region load", ca_auto, "2026-03-01"),
    ]
    all_ok = True
    for title, facts, as_of in cases:
        res = price(facts, as_of, ctx)
        _print_breakdown(title, facts, as_of, res)
        ok = _reconcile(res) and price(facts, as_of, ctx) == res  # reconciles & idempotent
        all_ok = all_ok and ok
        print(f"   reconcile+idempotent: {'PASS' if ok else 'FAIL'}")
    print("\n" + ("ALL CHECKS PASS" if all_ok else "CHECKS FAILED"))
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
