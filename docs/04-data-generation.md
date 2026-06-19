# 04 — Data Generation

How the v1 dataset is actually built. Principle 6: **code writes the facts, AI
writes the flavor.** Principle 2: **everything derives from a master seed.**

## Architecture

```
master_seed ─> reference tables (hand-authored, versioned in repo)
            ─> deterministic generators (code) ─> entities + policies + ledgers
            ─> rating engine (pure) ──────────> premiums + breakdowns
            ─> validator ─────────────────────> pass/fail (CI gate)
            ─> exporters ─────────────────────> peico.sqlite + peico.json
AI (offline, cached) ─> flavor: names, addresses, KB prose, persona seeds
```

### Hand-authored (in repo, reviewed like code)
The "designed" core — small, high-leverage, not generated:
- `product_lines`, `tiers`, `coverages`, `tier_coverage_defaults`
- `eligibility_rules` (with `reason_doc` links)
- `rate_tables` payloads (base rates + factor curves), versioned
- `promotions`, `discounts` (with `stack_order`)
- `regions`, state rule branches
- `kb_documents` (the policy/underwriting/compliance/glossary corpus)

These define the *physics* of the world. Keep them in readable source
(YAML/JSON5 + comments) so quirks are reviewable.

### Code-generated (deterministic, seeded)
- `customers` (+ status mix, risk distribution, the ~8% legacy-mismatch quirk)
- `addresses` (state distribution matching the region set)
- `household_members`, `vehicles`, `dwellings`, `pets`, `travelers`
- `policies` + `policy_coverages` + `policy_objects` (respecting eligibility!)
- `suitability_records` (including some `UNSUITABLE`/grandfathered-mis-sale seeds)
- `bundles`, `loyalty_ledger` (+ balance cache, + pre-2019 no-expiry entries)
- `payments`, `claims`, `bi_signals`
- premiums via the rating engine

Generators must **never** emit an ineligible policy except where a *documented*
legacy quirk intends it (e.g., grandfathered tier) — and those are tagged so the
validator allows them.

### AI-generated (offline, cached as data files)
Run once, commit the output, so the dataset stays deterministic:
- Realistic names/addresses (or use Faker with a seed — cheaper, no LLM).
- KB document **prose** (the policy language, the howto articles) — AI drafts,
  human reviews, then it's frozen in `kb_documents`.
- **Scenario/persona seeds** for future tasks (kept in a separate `scenarios/`
  area, not in the live DB).

Never let the AI step feed a number the validator checks.

## Volume targets (v1, tunable)
Big enough to be realistic and to support many distinct tasks; small enough to
snapshot fast and host on a static site.

| Entity | Target |
|---|---|
| customers | ~5,000 (≈55% CUSTOMER, 45% PROSPECT) |
| policies | ~9,000 active across 10 lines |
| vehicles/dwellings/etc | as implied by policies |
| bundles | ~1,200 households |
| kb_documents | ~120 |
| promotions | ~25 (mix of active/expired/retired-rider) |
| grandfathered policies | ~300 (HERITAGE/EVERGREEN_CLASSIC) |
| loyalty_ledger entries | ~80,000 |

Provide a `--scale` knob (tiny/small/full) so contributors can generate a 50-row
fixture for tests in <1s.

## Determinism mechanics
- Single `master_seed`; each generator derives a sub-seed by hashing
  `(master_seed, entity_name)` so adding one generator doesn't reshuffle others.
- No `now()` anywhere. A single `WORLD_ANCHOR_DATE` constant defines "today" for
  the snapshot; all dates are offsets from it. The future harness overrides
  `as_of` per scenario but the *stored* dataset is anchored once.
- Re-run with same seed must produce byte-identical `peico.sqlite` (hash in CI).

## Outputs
- `peico.sqlite` — canonical, for the future harness (snapshot/restore per task).
- `peico.json` (+ per-table NDJSON) — for the website visualizer.
- `data_card.md` — auto-generated stats: counts, distributions, quirk inventory,
  validator report. Ships with every dataset version.

## Build pipeline (CI)
1. Generate at `--scale full` with the committed seed.
2. Run the validator (all rules in `02` §validator). Fail the build on any error.
3. Recompute every premium; assert equality with stored.
4. Hash the artifacts; compare to the committed hash (detects accidental
   nondeterminism).
5. Emit `data_card.md`.
