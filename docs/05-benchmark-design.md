# 05 — Benchmark Design (forward-looking)

v1 ships only the dataset, but the dataset must be designed to support this. This
doc records the target so we don't paint ourselves into a corner. Nothing here is
built yet.

## The loop (τ-bench shaped)

```
   ┌──────────────┐  start / turn(customer_msg)   ┌──────────────┐
   │ User         │ ────────────────────────────> │   Agent      │   query / write / rate
   │ Simulator    │ <──────────────────────────── │ (any impl,   │ ──────────────────────┐
   │ (bench owns  │     reply (+ terminate?)       │  own tools)  │ <─────────────────────┘
   │  + powers it)│                                └──────────────┘   rows / changeset
   └──────────────┘                                       │
                                                          ▼
                                          Environment service (bench)
                                          per-session copy of peico.sqlite
After the conversation ends:
   changeset checker ── session DB diff (seed→final) vs expected ── when transactional
   rubric LLM-judge  ── correctness + good-faith engagement ── every task
```

## Access model (the contract)

Specified in full in `07-interface-and-access.md` and `08-agent-interface-and-harness-spec.md`.
Summary: the bench does **not** define a tool API. It exposes the **environment as a
service** — `query(sql)` (read), `write(sql)` (mutate the session copy; returns the
changeset), and physics utilities like `rate()` — and each agent composes its own
tools and loop over those primitives, in any language. Reads and writes are both raw
SQL; rule enforcement lives in the **expected outcome**, not the write path
(Principle 9). The dataset's `eligibility_rules`, `tiers.sellable`,
`requires_suitability`, etc. are what `rate()` and `query` read. Navigating the
gnarly schema is the skill.

### Difficulty axis: which utilities are exposed
Same task, same checker, two ceilings — **easy mode** exposes the physics helpers
(`rate`, eligibility), **hard mode** withholds them so the agent must `query` the
rule rows + read the wiki and compute price/eligibility itself before writing.
Separates strong from weak models without authoring new content.

## Scoring (two gates, per Principle 5)

Grading is on **outcomes, not tool calls** (every agent's tools differ). Two checks:

1. **Changeset** (when the task changes state) — the session DB diff (seed→final)
   must equal the task's expected changeset: required rows present with correct
   values (tier, premium, coverages, bundle, loyalty), and **nothing else mutated**.
   `final_premium_cents` must match the rating engine exactly.
2. **LLM-judge** (every task) — rubric over the transcript: required disclosures
   present, no mis-sale, correct refusal on negative-space tasks, and good-faith
   engagement (did the rep actually address the customer). Pinned model, structured
   output.

A task passes when all its required checks pass **and** the conversation completed
(the agent signalled terminate before `max_turns`); an incomplete conversation fails
by default. There is no separate "process legality" score. Report `pass@1` and
`pass^k` (consistency across k seeds) — agents that only sometimes get it right
should not look solved.

## User simulator (don't underweight this)

Each task ships a persona file:
- **identity & facts** (some true, some misstated — `annual_miles` low-balled,
  health omitted).
- **hidden goal** (what they actually want vs. what they say first).
- **constraints** (budget ceiling, won't switch banks, etc.).
- **non-disclosure list** — facts they reveal *only if explicitly asked*. This is
  the main difficulty lever; without it tasks are trivial.
- **reaction rules** — how the customer responds to what the rep surfaces, incl.
  things the customer *has but forgot* (e.g. a SEQUOIA pet policy after the pet died
  — the goal is for the rep to discover it via reads and advise dropping it). The
  customer never reads the DB, so every fact it must react to is authored here.
- **stop conditions** — when the customer is satisfied. The **rep speaks first**
  (welcome) and **last** (closing); the customer expresses satisfaction and the rep
  closes with a terminate signal.

The simulator is a separate, fixed model+prompt that **the bench owns and powers**
(the keystone of honesty — the agent can't fabricate customer turns), versioned so
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
- The benchmark itself reports **only correctness** (score). Token/cost/latency are
  **not** part of grading — they're a property of a given agent+model, surfaced
  separately (e.g. the website page running the *reference* agent across models with
  score + cost + latency), not of the bench.
- Bench is **versioned**; contamination is fought by rotating/withholding test
  tasks and by spot-running submitted agents/transcripts.

## Cost reality
Each task = multi-turn agent↔simulator + judge, × k seeds, × every leaderboard
model. Insurance conversations run long. Budget for this before scaling task
count; keep a cheap `--smoke` subset for development.
