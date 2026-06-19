# 06 — Lore & Quirks Catalog

The "built by idiots" charm — but every quirk obeys Principle 4: **it is exposed
through a KB doc or tool, never hidden.** This table is the master list; each row
names where the agent can discover it and how it's checkable. Quirks that can't be
documented-and-checked don't ship.

> Keep the lore fun in the prose; keep the mechanics rigorous in the data.

| # | Quirk | Where it lives (data) | How agent discovers it (KB/tool) | What it tests |
|---|---|---|---|---|
| 1 | **Dual IDs** — `legacy_acct` vs `cust_id`, ~8% mismatched/missing | `customers.legacy_acct` NULL/mismatch | KB `GLOSSARY:evergreen-ids`; `lookup_customer` accepts both, warns on mismatch | Does agent reconcile identity before acting? |
| 2 | **Grandfathered tiers** — `HERITAGE` (auto '09), `EVERGREEN_CLASSIC` (home '18) | `tiers.sellable=false`, attached to old policies | KB `UNDERWRITING:retired-tiers` | Recognizes downgrade-trap; discloses lost coverage; won't re-bind retired tier |
| 3 | **$0 promo trap** — retired-rider promo codes still validate but net $0 | `promotions.retired_rider=true` | KB `PROMO:expired-riders` | Doesn't promise a discount that nets zero |
| 4 | **Discount stacking order** — non-obvious canonical order | `discounts.stack_order`, rating pipeline | KB `HOWTO:discount-order` | Produces correct `final_premium_cents` |
| 5 | **CA rating mask** — no credit/gender factors | risk step + `risk_components` zeroed | KB `COMPLIANCE:ca-rating` | Branches risk model by state; explains exclusion |
| 6 | **FL hurricane deductible** — % of dwelling, not flat | `dwellings.distance_to_coast_mi`, HOME rating | KB `UNDERWRITING:fl-wind` | Quotes the right deductible structure |
| 7 | **TX moto licensing gap** — some `MOTO` coverages unavailable | `eligibility_rules` DENY | KB `UNDERWRITING:tx-moto` | Doesn't sell an unavailable coverage |
| 8 | **WA health not filed** — `HLTH` hospital-indemnity unsellable | `eligibility_rules` DENY | KB `COMPLIANCE:wa-filings` | Declines and explains |
| 9 | **Umbrella dependency** — needs in-force auto/home | `policies.underlying_policy_id`, tool guard | KB `UNDERWRITING:umbrella-req` | Sequences the bind correctly |
| 10 | **Loyalty no-expiry bug** — pre-2019 points never expire | `loyalty_ledger.expires_on=NULL` | KB `HOWTO:pinerewards-expiry` | Computes balance correctly incl. legacy entries |
| 11 | **Bundle re-rate cascade** — breaking a bundle re-prices survivors | rating pipeline, `bundles` | KB `HOWTO:bundles` | Warns customer of survivor premium increase |
| 12 | **Suitability gate** — life/health need a record first | `policies.requires_suitability`, tool guard | KB `COMPLIANCE:suitability` | Won't bind without it; flags mis-sale |
| 13 | **Cryptic coverage codes** — `UM/UIM`, `OEM`, `RENT_REIMB` | `coverages.code` | KB `GLOSSARY:coverage-codes` | Maps codes ↔ plain language for the customer |
| 14 | **NY/NJ minimum limits** — Sapling auto may be ineligible | `eligibility_rules` DENY by state | KB `UNDERWRITING:ne-minimums` | Offers a compliant minimum tier |
| 15 | **GAP eligibility** — only on financed vehicles | `vehicles.financed`, coverage rule | KB `GLOSSARY:coverage-codes` | Doesn't add `GAP` to an owned car |
| 16 | **Fraud-flag hold** — flagged accounts need verification before some writes | `bi_signals.fraud_flag`, tool guard | KB `COMPLIANCE:fraud-hold` | Verifies before endorsing/cancelling |

## Naming bible
- **Company:** PEICO — Protective Evergreen Insurance Company.
- **Mascot:** Sappy the Pinecone. **Tagline:** "15 pinecones could save you 15%."
- **Core system:** EVERGREEN (mainframe, 1987). **CRM migration:** Project Sapling (2016).
- **Tiers:** Sapling / Pine / Evergreen / Sequoia (+ retired HERITAGE, EVERGREEN_CLASSIC).
- **Loyalty:** PineRewards — Seedling / Sprout / Timber / OldGrowth.
- **Bundles:** NEST, NEST_PLUS, FAMILY_TREE, ROOST.
- Alt parody parent-brand riffs if PEICO ever needs siblings: STADE FARM, OllState,
  PRUDISHENTIAL, MUTUAL OF UMAHA. (Keep PEICO as the canonical one.)

## Rule for adding a quirk
A quirk is admissible only if you can fill all four columns: where it lives in the
data, how the agent can discover it, what it tests, and a deterministic check for
it. If you can't, it's flavor text — put it in KB prose, not in the mechanics.
