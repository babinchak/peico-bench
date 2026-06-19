# 00 — Design Principles (non-negotiable)

These rules exist because they are the ones people get wrong. Everything in the
dataset is designed in service of them, even though v1 ships no harness. Violate
these and the entire dataset has to be regenerated when the harness arrives.

## 1. Complex world, crisp tasks

The world model may be arbitrarily baroque. Every **task** (later) must have a
**deterministic, machine-checkable success condition**. The litmus test: *if the
author cannot write code that returns pass/fail for a task, the task does not
exist.* If a future scenario can't be checked deterministically, the world is too
complex *for that scenario* — not the other way around.

## 2. Determinism is sacred

The dataset and the rating engine must be **fully reproducible**:

- **Seeded generation.** All generated data derives from a fixed master seed.
  Same seed → byte-identical dataset.
- **Pure pricing.** Premium = `f(policy facts, rate tables, effective date)` with
  **no wall-clock and no RNG**. The "current date" is an **explicit input**, never
  `now()`.
- **Frozen time per scenario.** Promotions, rate versions, and risk scores are
  resolved against an injected `as_of` date. Two runs of the same scenario at the
  same `as_of` produce identical numbers.

If running the same thing twice yields different data, it is not a benchmark.

## 3. Every assertable fact is a real column

Anything a future task might check — premium, tier, coverage limit, discount
applied, loyalty points, who owns the policy — must be a **first-class, queryable
field**, not something inferred from prose. Scoring is a DB diff; the DB must hold
the truth.

## 4. Quirks are documented, never secret

Every legacy quirk (grandfathered tiers, weird discount stacking order,
state-specific eligibility, cryptic codes) must be discoverable by the agent
through a **knowledge-base document or a tool**. We measure navigation skill, not
recall of undocumented trivia. See `06-lore-and-quirks.md` — each quirk row names
the doc/tool that exposes it.

## 5. Programmatic-primary scoring

- **Objective outcomes → code.** Bound at right tier? Correct premium? Right
  discount? Only the intended records mutated? All deterministic assertions.
- **Soft/regulatory outcomes → rubric LLM-judge, minimized.** Required disclosure
  made? Mis-selling avoided? Correct refusal? Rubric + structured output, never
  free-form vibes. Keep the judge's surface area as small as possible — it is the
  weakest, most-attacked link.

A useful invariant: a task's score should be **mostly** recoverable from the DB
diff alone, with the judge adjusting only the soft margin.

## 6. AI writes flavor, code writes facts

The relational, numeric, internally-consistent core (schema, IDs, foreign keys,
premiums, rate tables) is produced by **deterministic code generators**. AI is
used only for **flavor**: names, addresses, policy-document prose, scenario ideas,
customer personas. Never let an LLM invent a number the checker depends on.

## 7. Negative space is content

The most discriminating tasks are the ones where the right answer is "no":
decline, refuse, disclose-then-decline, escalate, do-not-upsell. Design the world
so these are *possible and checkable* — ineligible customers, suitability
failures, prohibited cross-sells, regulated states. A bench that only rewards
"close the sale" measures salesmanship, not judgment.

## 8. Rules live as data, not code — one source, three consumers

The eligibility/discount/promo/tier logic is authored as **declarative rows**
(`eligibility_rules`, `discounts.stack_order`, `promotions.*`, tier sellability),
not buried in code. The same rows are read by three consumers: the **rating
engine** that executes them, the **agent** that can `SELECT` and reason from them,
and the **website** that renders them. This is why the engine and the database can
never disagree, and why a task can ask the agent to *explain* a rule as well as
*obey* it. Pricing curves may stay as opaque `rate_tables.payload` behind the
`quote` tool; it is the eligibility/discount/promo logic that must be inspectable.
See `07-interface-and-access.md`.

## 9. Writes are rule-enforcing tools; reads are wide open

Mutation happens **only** through tools that enforce the world's rules — never via
raw SQL — because the score is a DB diff and raw `UPDATE` lets an agent satisfy the
diff without doing the work. Reads, being pure, are exposed broadly (read-only SQL
+ wiki + engine query tools): navigating the gnarly schema *is* the skill under
test. See `07-interface-and-access.md`.

## 10. Internal consistency is testable

The dataset ships with a **validator**: every premium recomputes from the rating
engine, every FK resolves, every loyalty balance reconciles to its ledger, every
bundle's members exist, every grandfathered policy points at a real (possibly
retired) tier. The validator runs in CI. A dataset that fails its own validator is
a bug, not a quirk.
