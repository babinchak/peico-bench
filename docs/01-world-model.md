# 01 — World Model: PEICO

This is the domain. It is intentionally large. Every element here must map to a
real schema construct (`02-data-model.md`) and, where it carries a number, to the
rating engine (`03-rating-engine.md`).

> Conventions: tiers are tree-themed (on-brand for an evergreen mascot). All money
> is USD integer **cents** in the data model (display dollars in docs). All dates
> are resolved against an injected `as_of`.

---

## 1. Company & systems lore

- **PEICO** = Protective Evergreen Insurance Company. Direct-to-consumer.
- Core system **EVERGREEN** (mainframe, b. 1987). Bolt-ons accreted over decades.
- Two customer identifiers coexist and don't fully reconcile:
  - `legacy_acct` — 9-char alphanumeric from EVERGREEN (e.g., `EVG4471Q2`).
  - `cust_id` — modern UUID from the 2016 "Project Sapling" CRM migration.
  - ~8% of customers have a `legacy_acct` but a *mismatched or missing* CRM link.
    This is a deliberate, documented quirk (see `06-lore-and-quirks.md`).

---

## 2. Product lines (residential consumer only)

No commercial/business lines. Ten lines, grouped:

| Line | Code | Notes |
|---|---|---|
| Auto | `AUTO` | The flagship. Richest rating, most coverages. |
| Homeowners | `HOME` | Dwelling, structure, contents, liability. |
| Renters | `RENT` | Contents + liability, no dwelling. |
| Condo | `CONDO` | HO-6 style; carves around the HOA master policy. |
| Term Life | `LIFE_T` | Suitability-regulated. |
| Whole Life | `LIFE_W` | Suitability-regulated; cash value. |
| Supplemental Health | `HLTH` | Accident / critical-illness / hospital indemnity. **Not ACA major-medical** (kept narrow on purpose). |
| Travel | `TRVL` | Per-trip and annual multi-trip. |
| Personal Umbrella | `UMBR` | Requires an underlying auto or home policy. |
| Pet | `PET` | Accident & illness; fun, low-stakes line. |

**Specialty sub-lines under AUTO** (own coverage quirks): Motorcycle (`MOTO`),
RV (`RV`), Boat (`BOAT`), Classic/Collector (`CLSC`).

### Cross-line dependency rules (checkable)
- `UMBR` **cannot** be bound without an in-force underlying `AUTO` or `HOME`.
- `CONDO` liability assumes an HOA master policy; the master-policy deductible is
  a field that affects the loss-assessment coverage.
- `LIFE_*` and `HLTH` require a **suitability record** before binding (see §8).

---

## 3. Tiers

Every line offers tiers from this ladder (not all lines use all four):

| Tier | Theme | Position |
|---|---|---|
| **Sapling** | entry | minimal limits, high deductible, cheapest |
| **Pine** | standard | the default most customers land on |
| **Evergreen** | preferred | richer limits, added coverages |
| **Sequoia** | premium | max limits, concierge claims, lowest deductibles |

**Grandfathered / retired tiers** (still attached to legacy customers, not
sellable to new ones) — these are *load-bearing quirks*:
- `HERITAGE` (Auto, retired 2009) — has a coverage combination no current tier
  offers; cannot be re-bound once dropped.
- `EVERGREEN_CLASSIC` (Home, retired 2018) — different wind/hail deductible math.

A future task: "customer wants to upgrade off `HERITAGE`" — agent must recognize
the downgrade-trap (they lose a coverage) and disclose it. Checkable.

---

## 4. Coverages (per line)

Each tier is a **bundle of coverage components** with limits/deductibles. Example
for `AUTO` (cryptic EVERGREEN codes preserved on purpose, with plain-language
names in the KB):

| Code | Meaning | Tier behavior |
|---|---|---|
| `BI` | Bodily Injury liability | limit rises by tier |
| `PD` | Property Damage liability | limit rises by tier |
| `UM/UIM` | Uninsured/Underinsured Motorist | optional below Evergreen |
| `COLL` | Collision | deductible falls by tier |
| `COMP` | Comprehensive | deductible falls by tier |
| `MED` | Medical Payments | Evergreen+ only |
| `RENT_REIMB` | Rental reimbursement | Evergreen+ only |
| `ROAD` | Roadside | Sequoia included; add-on elsewhere |
| `GAP` | Loan/lease gap | only if vehicle is financed (eligibility rule) |
| `OEM` | OEM parts guarantee | Sequoia only |

Other lines have their own component tables (see `02-data-model.md`). The point:
coverages are **rows**, not adjectives, so "did the agent add `MED`?" is a diff.

---

## 5. Geographic regions

Rating, eligibility, and regulation vary by **state**, grouped into **rating
regions** for table management. Ship a realistic subset of states for v1 (not all
50 — pick ~12 that span the regulatory spectrum):

| Region | Example states | Why included |
|---|---|---|
| `R-NE` | NY, NJ, MA | Heavy regulation, mandatory coverages, rate-filing rigor |
| `R-SE` | FL, GA, NC | Hurricane/wind-hail; FL is its own beast for HOME |
| `R-MW` | IL, OH, MI | "Normal" baseline rating |
| `R-SW` | TX, AZ | TX auto quirks; hail |
| `R-W` | CA, WA | CA bans certain auto rating factors (documented quirk) |

### State-level rules (all documented, all checkable)
- **CA**: auto rating **may not** use credit-based insurance score; gender
  prohibited. The risk model must branch on state.
- **FL**: HOME requires a separate hurricane deductible (% of dwelling, not flat).
- **NY/NJ**: minimum BI/PD limits higher than baseline; Sapling auto may be
  ineligible.
- **TX**: some `MOTO` coverages unavailable (historical licensing — a pure legacy
  quirk).
- **WA**: `HLTH` hospital-indemnity product not filed → not sellable.

Eligibility is a function `eligible(line, tier, coverage, state, as_of)`. Selling
an ineligible combination is a **failing** outcome.

---

## 6. Promotions

Time-bound, region-scoped, line-scoped discounts. Resolved against `as_of`.

| Field | Notes |
|---|---|
| `promo_code` | e.g., `SPRING24`, `PINEBUNDLE`, `WELCOME15` |
| `window` | `[start, end)` — only active if `as_of` inside |
| `scope` | line(s), tier(s), region(s), new-vs-existing |
| `effect` | % off, $ off, free-coverage, fee-waiver |
| `stacking` | which other promos/discounts it stacks with, and **order** |
| `caps` | max $ benefit; min premium floor |

**Quirks (documented):** `WELCOME15` only applies to *new* customers' *first*
policy; `PINEBUNDLE` requires ≥2 active lines; some legacy promo codes still
validate but produce $0 because their rate rider was retired (a trap — agent
should not promise a discount that nets zero).

Stacking order matters and is **non-obvious** — the rating engine defines the
canonical order (`03-rating-engine.md §discounts`). Agents that apply discounts in
the wrong order produce a wrong premium → fail the diff.

---

## 7. Bundles

A bundle is a named grouping of ≥2 policies for one household that unlocks a
multi-line discount and shared billing.

| Bundle | Members | Benefit |
|---|---|---|
| `NEST` | Auto + Home | Flagship multi-line discount |
| `NEST_PLUS` | Auto + Home + Umbrella | Larger discount; Umbrella dependency satisfied |
| `FAMILY_TREE` | ≥3 lines incl. a Life or Health | Loyalty-point multiplier |
| `ROOST` | Renters + Auto | The "young customer" bundle |

Bundle discount interacts with promos and loyalty — defined explicitly in the
rating engine. Breaking a bundle (cancelling one member) must **re-rate** the
survivors (lose the discount) — a checkable cascade.

---

## 8. Suitability & disclosures (the "negative space")

For `LIFE_*` and `HLTH`, binding requires a **suitability record**:
- income, existing coverage, dependents, stated need, risk tolerance.
- A `LIFE_W` (whole life) sale to a customer whose suitability record indicates
  short-horizon need + tight budget is a **mis-sale** → judge-flagged failure.
- Required disclosures (free-look period, surrender charges, that whole life is
  not an investment account) must be present in the transcript → rubric check.

This is the core of the regulatory difficulty axis. It is *intentionally* where
"just close the sale" agents lose points.

---

## 9. Customer accounts

Each household/customer carries:

- Identity (`cust_id`, maybe `legacy_acct`), contacts, address (→ state → region).
- **Status**: `PROSPECT` (no active policy) vs `CUSTOMER` (≥1 active). Different
  flows, different promo eligibility.
- **Risk score** (`peico_risk`, 300–850, *insurance* risk not credit) — drives
  rate factor and eligibility. Components documented in `03-rating-engine.md`.
  Note: in CA, the credit-based component is zeroed by law.
- **Claims history**, **payment history**, **tenure**.
- **Loyalty** (see §10).
- **BI signals** (see §11).
- **Household members / drivers / insured items** (vehicles, dwellings, pets,
  travelers) — the rateable objects.

---

## 10. Loyalty — "PineRewards"

| Element | Detail |
|---|---|
| Points ledger | Earn on premium paid, tenure, bundle, on-time payment; redeem for fee waivers / deductible credits |
| Tiers | `Seedling → Sprout → Timber → OldGrowth` (by trailing-12mo points + tenure) |
| Perks | OldGrowth: accident forgiveness, free roadside, dedicated rep |
| Quirk | Points have a **24-month expiry**, FIFO; a documented bug grandfathered pre-2019 points to never expire |

Loyalty balance must reconcile to the ledger (validator rule). A future task:
"redeem points for a deductible credit" → assert ledger entry + balance + policy
deductible all move consistently.

---

## 11. Business-intelligence signals

Per-customer model outputs, stored as fields, used to make tasks realistic (and
to create "the upsell the agent should *not* make" scenarios):

| Signal | Range | Use |
|---|---|---|
| `churn_propensity` | 0–1 | Retention scenarios |
| `upsell_propensity` | 0–1 | Cross-sell scenarios |
| `price_sensitivity` | 0–1 | Whether a discount is needed to close |
| `clv_estimate` | $ | Prioritization |
| `fraud_flag` | bool/score | Some claims/changes require verification first |
| `contactability` | enum | Channel preferences |

These are **inputs to scenarios**, never themselves scored. They let a task say
"this customer is high churn + high price sensitivity" and check whether the agent
retained them within the discount authority it actually had.

---

## 12. Flows

- **New prospect → quote → bind.** Eligibility, suitability (if life/health),
  promo application, optional bundle.
- **Existing customer service.** Endorsements (add vehicle/driver/coverage),
  tier changes, address change (→ re-rate, maybe re-eligibility), cancellation,
  reinstatement, claims intake (limited), payment/billing, loyalty redemption.
- **Retention.** Customer threatens to leave; agent has bounded discount
  authority; goal is retain *without* exceeding authority or mis-disclosing.
- **Cross-sell / bundle.** Offer a second line; must respect suitability and the
  do-not-upsell signals.

Each flow has a defined set of legal tool calls and a defined correct end-state —
that's what makes it benchmarkable later.

---

## Open design questions (flagged for you)

1. **State count for v1** — I scoped ~12 states across 5 regions. Want all 50
   (more generation work, marginal benefit) or this representative subset?
2. **Health line** — I deliberately kept it *supplemental* (accident/CI/hospital
   indemnity) to avoid the ACA major-medical morass. OK, or do you want full major
   medical with its own regulatory hell?
3. **Claims** — full claims lifecycle is a whole second world. I scoped it to
   *intake only* (FNOL) for v1. Expand later?
4. **Tier naming** — tree theme (Sapling/Pine/Evergreen/Sequoia) vs plain
   Bronze/Silver/Gold/Platinum. I went on-brand; easy to swap.
