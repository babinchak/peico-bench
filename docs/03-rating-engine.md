# 03 — Rating Engine (deterministic pricing)

This is the load-bearing piece. If pricing is deterministic and pure, the whole
benchmark is checkable; if it isn't, nothing downstream can be scored. Treat this
spec as the source of truth that `policies.final_premium_cents` and
`premium_breakdown` must reproduce exactly.

## Contract

```
price(policy_facts, as_of) -> { base_premium_cents, final_premium_cents, breakdown }
```

- **Pure.** No wall-clock, no RNG, no network. `as_of` is an explicit argument.
- **Versioned tables.** Selects the `rate_tables` row for (`line`,`region`,`as_of`).
- **Deterministic ordering.** Discounts/promos apply in a single canonical order
  (below). Reordering changes the result, so the order is fixed and documented.
- **Integer cents throughout**, with a single defined rounding rule per step
  (round half-up at each multiplicative step, to the cent).

## Pipeline (canonical order — do not reorder)

```
1. BASE          base rate for line+tier+region+term (rate_tables payload)
2. EXPOSURE      × per-object exposure (vehicles, dwelling RC, travelers, ...)
3. RISK FACTORS  × product factor curves keyed on rateable attributes
                   (age, vehicle symbol, roof age, claims, peico_risk, ...)
                   ── state masking applied here (CA: drop credit & gender) ──
4. COVERAGE      + priced coverage components (policy_coverages contributions)
5. FEES/TAXES    + state fees, policy fee, fractional-pay surcharge
   = base_premium_cents  (the pre-discount premium recorded on the policy)

6. DISCOUNTS     × multiplicative discounts in stack_order:
                   a. multi-line / bundle
                   b. loyalty-tier
                   c. behavioral (safe-driver, paperless, paid-in-full)
7. PROMOS        apply active promos (as_of in window, scope matches),
                   respecting stacks_with and caps; retired-rider promo = $0
8. FLOORS/CAPS   apply min-premium floor and max-benefit caps
   = final_premium_cents
```

`breakdown` is an ordered list of `{step, code, input, factor_or_amount, running_total}`
so the website can show the math and the validator can recompute it.

## Risk score (`peico_risk`, 300–850)

A documented, auditable composite stored in `customers.risk_components`:

| Component | Weight | Notes |
|---|---|---|
| Prior claims frequency/severity | high | |
| Payment history | medium | from `payments` |
| Tenure | medium | longer = better |
| Credit-based insurance score | medium | **zeroed in CA by law** |
| Object/exposure risk | line-specific | vehicle symbol, roof age, coast distance |

State masking lives in the risk step *and* is reflected in `risk_components` (the
masked component is present but weighted 0) so the website can show "this factor
was excluded due to CA law" — turning a quirk into a visible, fair rule.

## Worked example (illustrative, not final numbers)

`AUTO`, `PINE` tier, region `R-MW`, 12-month term, one financed vehicle,
`peico_risk=720`, customer is `CUSTOMER` with `NEST` bundle and `Timber` loyalty,
`as_of = 2026-03-01`, promo `SPRING24` active.

```
1 BASE        $640.00
2 EXPOSURE    ×1.10  -> $704.00
3 RISK        ×0.92  -> $647.68   (good risk; CA mask N/A in R-MW)
4 COVERAGE    +$58.00 (GAP eligible: financed) -> $705.68
5 FEES        +$12.00 -> $717.68   == base_premium_cents = 71768
6 DISCOUNTS   ×0.85 (NEST) ×0.95 (Timber) -> $579.53
7 PROMOS      SPRING24 -10%, stacks_with bundle -> $521.58
8 FLOOR       min $350 ok -> final_premium_cents = 52158
```

Every line here is a `breakdown` entry. Change `as_of` to after the `SPRING24`
window and step 7 vanishes — deterministically.

## Why this guarantees benchmarkability

A future task "rebind this customer onto Evergreen and apply their loyalty
discount" has exactly one correct `final_premium_cents` given the facts and
`as_of`. The harness asserts that number. No judge needed for the math.

## Implementation notes
- Ship the engine as a small pure module imported by both the generator (to fill
  `final_premium_cents`) and the validator (to verify it). Single source of truth.
- Property-test it: random valid policy facts → assert `breakdown` running totals
  reconcile and re-pricing is idempotent.
