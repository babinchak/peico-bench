# 02 — Data Model (relational schema)

The schema is the contract. Scoring is a diff against these tables, so every
assertable fact lives here as a typed column. Money is integer **cents**. Dates
are ISO `date`. IDs are UUID unless noted. `as_of` is never stored — it's an
input.

Storage for v1: ship as **SQLite** (single file, trivially snapshot/restore for a
future harness) plus a **JSON export** for the website. The schema below is
engine-agnostic.

---

## Conventions

- `*_cents` integer money. `*_bps` integer basis points for rates/factors.
- `created_at` / `updated_at` are **generation-time** stamps derived from seed +
  `as_of` anchor, never `now()`.
- Soft enums are stored as short codes with a lookup table so the website can
  render labels and the KB can document them.

---

## Core entities

### `customers`
| col | type | notes |
|---|---|---|
| `cust_id` | uuid PK | modern CRM id |
| `legacy_acct` | text NULL | EVERGREEN id; may be NULL or mismatched (quirk) |
| `status` | enum | `PROSPECT` \| `CUSTOMER` |
| `first_name`,`last_name` | text | AI flavor |
| `dob` | date | drives age factor / life suitability |
| `email`,`phone` | text | |
| `address_id` | fk→addresses | |
| `peico_risk` | int 300–850 | insurance risk score |
| `risk_components` | json | breakdown (so it's auditable & CA-maskable) |
| `tenure_start` | date | first-ever policy date |
| `loyalty_tier` | enum | derived, but stored for diffability |
| `created_at` | date | |

### `addresses`
`address_id` PK, lines, `city`, `state`, `zip`, `region` (fk→regions). State
drives region, eligibility, and tax/fees.

### `regions`
`region` PK (`R-NE`…), label, notes. Static reference.

### `household_members`
People on an account who aren't the primary (spouse, drivers, dependents).
`member_id` PK, `cust_id` fk, role enum, `dob`, driver attributes (license
status, years licensed, incidents) for auto rating.

---

## Rateable objects

### `vehicles`
`vehicle_id` PK, `cust_id` fk, year/make/model, `vin` (fake, checksum-valid),
`usage` enum (commute/pleasure/business-excluded), `annual_miles`,
`financed` bool (gates `GAP`), `garaging_address_id`.

### `dwellings`
`dwelling_id` PK, `cust_id` fk, type (home/condo/rental), `year_built`,
`construction`, `roof_age`, `sq_ft`, `replacement_cost_cents`, `protection_class`,
`distance_to_coast_mi` (drives FL/SE wind rules).

### `pets`, `travelers`, `insured_items`
Line-specific rateable objects, same pattern: PK, owner fk, attributes that feed
rating.

---

## Products, tiers, coverages (reference tables)

### `product_lines`
`line` PK (`AUTO`…), label, `requires_suitability` bool, `requires_underlying`
enum NULL (for `UMBR`).

### `tiers`
`tier_id` PK, `line` fk, `code` (`SAPLING`…/grandfathered codes), `sellable` bool
(false for retired tiers), `retired_on` date NULL.

### `coverages`
`coverage_id` PK, `line` fk, `code` (`BI`,`COLL`…), label, `kind` (limit /
deductible / flag), `unit` ($, %, bool).

### `tier_coverage_defaults`
Which coverages a tier includes and their default limit/deductible. PK
(`tier_id`,`coverage_id`), `default_value`, `included` bool, `editable` bool.

### `eligibility_rules`
Drives `eligible(line,tier,coverage,state,as_of)`.
`rule_id` PK, scope columns (`line`,`tier_id` NULL,`coverage_id` NULL,`state` NULL),
`effect` (`ALLOW`/`DENY`), `effective` range, `reason_doc` (→ KB doc id).
**Every DENY names the KB doc that explains it.**

---

## Policies (the live state)

### `policies`
| col | type | notes |
|---|---|---|
| `policy_id` | uuid PK | |
| `cust_id` | fk | owner |
| `line` | fk | |
| `tier_id` | fk | may point at a retired tier (grandfathered) |
| `status` | enum | `QUOTE` \| `ACTIVE` \| `CANCELLED` \| `LAPSED` \| `PENDING` |
| `effective_date`,`expiration_date` | date | |
| `term_months` | int | 6 or 12 |
| `base_premium_cents` | int | pre-discount, from rating engine |
| `final_premium_cents` | int | post discounts/promos/loyalty/fees |
| `premium_breakdown` | json | every factor & discount, in canonical order |
| `underlying_policy_id` | fk NULL | for `UMBR` |
| `bundle_id` | fk NULL | |
| `created_at`,`updated_at` | date | |

`final_premium_cents` and `premium_breakdown` **must recompute** from the rating
engine given the policy facts + `as_of` (validator rule §8 of principles).

### `policy_coverages`
The actual coverage instances on a policy (diverged from tier defaults via
endorsement). PK (`policy_id`,`coverage_id`), `value`, `premium_contribution_cents`.

### `policy_objects`
Links policies to rateable objects (vehicle/dwelling/pet/traveler). M:N.

### `suitability_records`
`suit_id` PK, `cust_id` fk, `line` fk, income, dependents, existing_coverage,
stated_need, horizon, risk_tolerance, `completed_at`, `outcome` enum
(`SUITABLE`/`UNSUITABLE`/`NEEDS_REVIEW`). Required before `LIFE_*`/`HLTH` bind.

---

## Pricing / promos / discounts

### `rate_tables`
Versioned. `rate_table_id` PK, `line`, `region`, `version`, `effective` range,
`payload` json (base rates + factor curves). Pricing selects the version whose
range contains `as_of`. **Versioning is why pricing is reproducible across dates.**

### `promotions`
`promo_code` PK, scope (lines/tiers/regions/new-vs-existing), `window`,
`effect` json, `stacks_with` json, `caps` json, `active` bool,
`retired_rider` bool (the "$0 trap" flag), `doc_id` fk→KB.

### `discounts`
Non-promo discounts (multi-line/bundle, loyalty, safe-driver, paid-in-full,
paperless…). `discount_id` PK, `code`, `effect`, `stack_order` int (**canonical
application order**), `eligibility` json.

---

## Bundles & loyalty

### `bundles`
`bundle_id` PK, `cust_id`, `code` (`NEST`…), `discount_id` fk, `created_at`.
Members are the `policies` rows whose `bundle_id` points here. Breaking a bundle
re-rates survivors.

### `loyalty_ledger`
Append-only. `entry_id` PK, `cust_id`, `ts`, `delta_points` (+earn/−redeem/−expire),
`reason`, `expires_on` date NULL, `ref_policy_id` NULL.
`loyalty_balance` = sum of non-expired deltas; must equal a (stored, diffable)
`customers.loyalty_points` cache. The pre-2019 no-expiry bug is encoded as
`expires_on = NULL` on those entries.

---

## Activity & BI

### `claims` (FNOL-only for v1)
`claim_id` PK, `policy_id`, `reported_at`, `loss_date`, `type`, `status`
(`FNOL`/`OPEN`/`CLOSED`), `reserve_cents`, `fraud_score`.

### `payments`
`payment_id` PK, `cust_id`, `policy_id`, `due`, `paid_on` NULL, `amount_cents`,
`status` (`PAID`/`LATE`/`MISSED`). Feeds payment-history risk + loyalty.

### `bi_signals`
`cust_id` PK, `churn_propensity` bps, `upsell_propensity` bps,
`price_sensitivity` bps, `clv_cents`, `fraud_flag` bool, `contactability` enum.

---

## Knowledge base (what makes quirks fair)

### `kb_documents`
`doc_id` PK, `title`, `category` (`POLICY`/`UNDERWRITING`/`PROMO`/`COMPLIANCE`/
`HOWTO`/`GLOSSARY`), `body_md` text, `applies_to` json (lines/states), `version`.
The agent's future `search_kb` / `get_doc` tools read this. Every
`eligibility_rules.reason_doc`, every retired tier, every promo quirk, every
cryptic coverage code resolves to a row here. **This table is the antidote to
"memorize trivia."**

---

## Entity relationship sketch

```
customers ─┬─< policies >─┬─ tiers ── product_lines
           │              ├─ policy_coverages >── coverages
           │              ├─ policy_objects >── vehicles/dwellings/pets/...
           │              ├─ bundles
           │              └─ rate_tables (by line+region+version+as_of)
           ├─< household_members
           ├─< suitability_records
           ├─< loyalty_ledger     (cache: customers.loyalty_points)
           ├─< payments / claims
           ├─ bi_signals (1:1)
           └─ addresses ── regions

promotions / discounts ── apply during rating (canonical order) ── premium_breakdown
kb_documents ── referenced by eligibility_rules, promotions, tiers (quirk docs)
```

## Validator (ships with the data)
1. All FKs resolve.
2. Every `policies.final_premium_cents` recomputes from the rating engine.
3. Every `loyalty_points` cache equals its ledger sum.
4. Every bundle has ≥2 active members; survivors' premiums reflect the discount.
5. Every retired tier is `sellable=false` and only attached to pre-`retired_on`
   policies.
6. Every `DENY` eligibility rule and every quirk has a live `doc_id`.
7. `UMBR` policies have a valid in-force `underlying_policy_id`.
