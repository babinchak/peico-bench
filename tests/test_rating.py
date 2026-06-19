"""Spec/property tests for the rating engine (docs/03-rating-engine.md)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from peico import rating  # noqa: E402

DB = ROOT / "out" / "peico.sqlite"
pytestmark = pytest.mark.skipif(not DB.exists(), reason="build out/peico.sqlite first")


@pytest.fixture(scope="module")
def ctx():
    return rating.load_context(DB)


def _auto(**over):
    facts = {
        "line": "AUTO", "tier": "PINE", "region": "R-MW", "state": "IL", "term_months": 12,
        "peico_risk": 720, "driver_age": 40, "annual_miles": 12000, "vehicle_age": 4,
        "incidents_5yr": 0, "coverages": ["GAP"], "billing_plan": "PAY_IN_FULL",
        "has_bundle": True, "loyalty_tier": "Timber", "paperless": True, "autopay": True,
        "status": "CUSTOMER", "active_lines": 2,
    }
    facts.update(over)
    return facts


def _reconciles(res) -> bool:
    prev = None
    for e in res["breakdown"]:
        if prev is not None and e["factor"] is not None and e["step"] != "EXPOSURE":
            if rating._mul(prev, e["factor"]) != e["running_cents"]:
                return False
        if prev is not None and e["amount_cents"] is not None and e["step"] != "FLOOR":
            if prev + e["amount_cents"] != e["running_cents"]:
                return False
        prev = e["running_cents"]
    return True


def test_pure_and_idempotent(ctx):
    f = _auto(promo_code="PINEBUNDLE")
    assert rating.price(f, "2026-03-01", ctx) == rating.price(f, "2026-03-01", ctx)


def test_breakdown_reconciles(ctx):
    for f, as_of in [(_auto(promo_code="PINEBUNDLE"), "2026-03-01"),
                     (_auto(region="R-W", state="CA"), "2026-03-01")]:
        assert _reconciles(rating.price(f, as_of, ctx))


def test_final_matches_last_breakdown_row(ctx):
    res = rating.price(_auto(promo_code="PINEBUNDLE"), "2026-03-01", ctx)
    assert res["final_premium_cents"] == res["breakdown"][-1]["running_cents"]


def test_promo_resolves_against_as_of(ctx):
    """Same facts, different as_of: promo applies inside window, vanishes after."""
    f = _auto(promo_code="SPRINGSAVE25", region="R-MW", has_bundle=False, loyalty_tier=None)
    inside = rating.price(f, "2025-04-01", ctx)["final_premium_cents"]
    after = rating.price(f, "2025-09-01", ctx)["final_premium_cents"]
    assert inside < after  # $75 off inside the spring-2025 window, nothing after


def test_region_load_increases_base(ctx):
    """CA (R-W) auto carries a region load over the Midwest reference."""
    mw = rating.price(_auto(region="R-MW", state="IL"), "2026-03-01", ctx)
    ca = rating.price(_auto(region="R-W", state="CA"), "2026-03-01", ctx)
    assert ca["base_premium_cents"] > mw["base_premium_cents"]


def test_retired_rider_promo_nets_zero(ctx):
    """GREENSTART validates but its rider was retired -> $0 benefit (the trap)."""
    f = _auto(promo_code="GREENSTART", has_bundle=False, loyalty_tier=None,
              status="CUSTOMER", region="R-MW")
    res = rating.price(f, "2026-03-01", ctx)
    promo_rows = [e for e in res["breakdown"] if e["step"] == "PROMO"]
    assert promo_rows and promo_rows[-1]["amount_cents"] == 0


def test_discounts_apply_in_stack_order(ctx):
    res = rating.price(_auto(), "2026-03-01", ctx)
    orders = [d["stack_order"] for code in
              [e["code"] for e in res["breakdown"] if e["step"] == "DISCOUNT"]
              for d in ctx.discounts if d["code"] == code]
    assert orders == sorted(orders)


def test_safe_driver_requires_clean_record(ctx):
    clean = rating.price(_auto(incidents_5yr=0), "2026-03-01", ctx)
    dinged = rating.price(_auto(incidents_5yr=2), "2026-03-01", ctx)
    clean_codes = {e["code"] for e in clean["breakdown"] if e["step"] == "DISCOUNT"}
    dinged_codes = {e["code"] for e in dinged["breakdown"] if e["step"] == "DISCOUNT"}
    assert "SAFE_DRIVER" in clean_codes and "SAFE_DRIVER" not in dinged_codes
