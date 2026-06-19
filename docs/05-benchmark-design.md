# 05 — Benchmark Design (forward-looking)

v1 ships only the dataset, but the dataset must be designed to support this. This
doc records the target so we don't paint ourselves into a corner. Nothing here is
built yet.

## The loop (τ-bench shaped)

```
        ┌─────────────┐     tool calls      ┌──────────────┐
        │   Agent     │ ──────────────────> │  Tool API     │ ──> peico.sqlite
        │ (system     │ <────────────────── │  (read/write) │     (per-task snapshot)
        │  under test)│     tool results    └──────────────┘
        └──────┬──────┘
               │ natural-language turns
        ┌──────▼──────┐
        │ User        │  persona + hidden goal + constraints + non-disclosure rules
        │ Simulator   │
        └─────────────┘
After the conversation ends:
   programmatic checker  ── DB diff vs expected end-state ── primary score
   rubric LLM-judge      ── disclosures / mis-selling / refusal ── soft margin
```

## Tool API (the contract)

The interface model is specified in full in `07-interface-and-access.md`. Summary:

- **Reads (wide open):** read-only SQL `query_db` over the per-task snapshot;
  wiki retrieval `search_kb` / `get_doc`; engine query tools `quote` (price
  preview) and `check_eligibility`. Navigating the gnarly schema is the skill.
- **Writes (rule-enforcing tools only, never raw SQL):** `bind_policy`,
  `endorse_policy`, `change_tier`, `apply_promo`, `cancel_policy`,
  `reinstate_policy`, `create_bundle`/`break_bundle`, `record_suitability`,
  `redeem_loyalty`, `open_fnol`, `update_contact`.

Every write tool enforces the world's rules (eligibility, suitability,
dependencies, fraud hold) and returns structured errors — so a bad agent *can*
make a wrong call, and the DB records it for the diff. The dataset's
`eligibility_rules`, `tiers.sellable`, `requires_suitability`, etc. are exactly
what these tools (and `query_db`) read.

### Difficulty axis: tool availability
Same task, same checker, two ceilings — **easy mode** exposes the engine tools
(`quote`/`check_eligibility`), **hard mode** withholds them so the agent must
`SELECT` the rule rows + read the wiki and compute eligibility/price itself before
writing. Separates strong from weak models without authoring new content.

## Scoring (programmatic-primary, per Principle 5)

A task defines an **expected diff**: the set of rows that must change (and their
target values) and the set that must **not** change. Score components:

1. **Outcome correctness** (largest weight) — required rows present with correct
   values (tier, premium, coverages, bundle, loyalty entries).
2. **No collateral damage** — nothing outside the allowed write-set mutated.
3. **Premium exactness** — `final_premium_cents` matches the rating engine.
4. **Process legality** — no illegal tool call succeeded (e.g., bound an
   ineligible tier, skipped suitability).
5. **Soft margin (judge, rubric)** — required disclosures present; no mis-sale;
   correct refusal/decline when the task is a negative-space task.

Report `pass@1` and `pass^k` (consistency across k seeds) — agents that only
sometimes get it right should not look solved.

## User simulator (don't underweight this)

Each task ships a persona file:
- **identity & facts** (some true, some misstated — `annual_miles` low-balled,
  health omitted).
- **hidden goal** (what they actually want vs. what they say first).
- **constraints** (budget ceiling, won't switch banks, etc.).
- **non-disclosure list** — facts they reveal *only if explicitly asked*. This is
  the main difficulty lever; without it tasks are trivial.
- **stop conditions** — when the customer ends the call (satisfied / frustrated /
  out of scope).

The simulator is a separate, fixed model+prompt, versioned with the bench, so
leaderboard comparisons are apples-to-apples.

## Task taxonomy (so the dataset covers them)
- **New-business bind** (eligibility + promo + maybe bundle).
- **Endorsement** (add vehicle/driver/coverage → re-rate).
- **Tier change** (incl. grandfathered downgrade-trap disclosure).
- **Retention** (bounded discount authority; don't over-discount).
- **Cross-sell/bundle** (respect suitability + do-not-upsell signals).
- **Suitability-gated life/health** (the mis-sale negative-space tasks).
- **Billing/loyalty** (redeem points → ledger+balance+deductible cascade).
- **Service** (address change → re-rate / re-eligibility; cancellation cascade).
- **"No" tasks** (ineligible request, fraud-flag hold, prohibited cross-sell).

Each taxonomy entry needs DB seed states that make it expressible — that's a
requirement *on the dataset*, tracked in `04`'s scenario seeds.

## Splits & leaderboard (self-report + held-out)
- **Dev split** (public): tasks + expected diffs published; people iterate.
- **Test split** (private): held out; used to verify self-reported numbers.
- Submissions report **score AND tokens/cost AND model**; a model that wins by
  burning 50× tokens is shown as such.
- Bench is **versioned**; contamination is fought by rotating/withholding test
  tasks and by spot-running submitted agents/transcripts.

## Cost reality
Each task = multi-turn agent↔simulator + judge, × k seeds, × every leaderboard
model. Insurance conversations run long. Budget for this before scaling task
count; keep a cheap `--smoke` subset for development.
