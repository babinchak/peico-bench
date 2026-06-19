# PEICO Insurance Agent Benchmark (`peico-bench`)

> A benchmark for LLM sales & service agents, set inside a deliberately gnarly,
> legacy-encrusted residential insurance company. **The complexity is the
> point** — but it is *load-bearing* complexity, not decoration.

## What this is

`peico-bench` measures how well an autonomous agent can act as a **sales and
service representative** for a fictional consumer insurance company, **PEICO**.
An agent is dropped into a multi-turn conversation with a simulated customer,
given a set of tools that read and write a realistic insurance database, and
scored on whether it **reached the right outcome and changed the right data** —
without mis-selling, violating regulation, or touching records it shouldn't.

It is closely modeled on Sierra's **τ-bench / τ²-bench** (user simulator + tool
API + database end-state assertion). If you haven't read those papers, read them
before contributing — this project reuses their core architecture.

## Why insurance

Insurance is an unusually good substrate for an agent benchmark:

- **Objective, checkable outcomes.** A policy is either bound at the right tier
  with the right premium, or it isn't. Most scoring is a database diff, not a
  vibe check.
- **The obvious action is often wrong.** Suitability rules, mandatory
  disclosures, state-by-state eligibility, and risk-based declines mean the
  highest-scoring move is sometimes *to not make the sale*. This is where weak
  agents fail and the benchmark earns its discrimination.
- **Real ambiguity from the customer side.** Customers don't know their own
  coverage needs, misstate facts, omit risk factors, and have hidden budgets —
  perfect fuel for a user simulator.
- **Legitimately complex world.** Product lines × tiers × regions × promotions ×
  bundles × loyalty × risk creates a combinatorially rich space without any
  artificial padding.

## The lore (and the quirk)

PEICO ("**P**rotective **E**vergreen **I**nsurance **CO**mpany") is a parody of a
big-brand direct insurer. Mascot: **Sappy the Pinecone**. Tagline: *"15 pinecones
could save you 15%."*

The conceit: PEICO's core system, **EVERGREEN**, is a mainframe first written in
1987 and layered on by decades of well-meaning people who did not talk to each
other. So the data model has grandfathered tiers nobody sells anymore, two
customer-ID systems that don't fully reconcile, promo codes with inconsistent
rules, cryptic coverage abbreviations, and products that exist in some states for
purely historical licensing reasons.

**Critical design rule:** every quirk lives in **retrievable documentation or a
tool the agent can query** — never only in the test author's head. We are
measuring *"can the agent navigate a gnarly real system correctly,"* not
*"did the agent memorize trivia."* Memorization tasks are unfair and useless.

## Roadmap

- **v1 — The Dataset (current).** A complete, internally-consistent, deterministic
  world: schema, all residential product lines, a deterministic rating engine,
  generated data, and the policy/knowledge-base documents. No harness yet. The
  dataset is designed so the harness slots in later for free.
- **v2 — The Harness.** Tool API, user simulator, per-task DB snapshot/reset,
  programmatic + rubric scoring.
- **v3 — The Tasks.** A dev split (public) and a held-out test split (private).
- **v4 — The Website.** Database visualizer + self-report leaderboard (score and
  token/cost reported together), held-out verification.
- **Later — Internal Triage Bench.** A separate product: an internal Q&A/triage
  agent over the same world. Explicitly out of scope until the above ships.

## Decisions locked so far

| Decision | Choice |
|---|---|
| v1 deliverable | The dataset only (all residential product lines) |
| Leaderboard integrity | Self-report + held-out private test split |
| Scoring model | Programmatic DB-diff primary; LLM-judge only for soft/regulatory checks |
| Build order | Docs → schema → generators → (later) harness |

## Repo layout

```
docs/
  00-design-principles.md   The non-negotiable rules (determinism, checkability)
  01-world-model.md         PEICO: product lines, tiers, regions, promos, loyalty, risk, BI
  02-data-model.md          Relational schema
  03-rating-engine.md       Deterministic pricing — the load-bearing piece
  04-data-generation.md     How the dataset is built (code for numbers, AI for flavor)
  05-benchmark-design.md    Forward-looking: tasks, scoring, simulator, leaderboard
  06-lore-and-quirks.md     The catalog of legacy quirks (each mapped to a doc/tool)
  07-interface-and-access.md  How the agent touches the world (writes=tools, reads=SQL+wiki)
```
