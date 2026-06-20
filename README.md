<p align="center">
  <img src="assets/peico-mascot.png" alt="Sappy the Pinecone" height="150" align="middle">
  &nbsp;&nbsp;
  <img src="assets/peico-letters.png" alt="PEICO" height="64" align="middle">
</p>

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

## What the bench owns vs. what you own

The benchmark is **agent-agnostic**. It owns the entire world and the rules of
the game; *you* own the player. The line between the two is the whole point — it's
what makes scores comparable across wildly different agents, and what keeps the
game honest (your agent can't write the customer's lines or grade its own work).

| The bench owns | Your agent implementation owns |
|---|---|
| **The world** — the EVERGREEN database, schema, generated data, and policy/KB documents | **The loop** — how it reasons, plans, and decides when it's done |
| **The customer** — the simulated customer, their persona, hidden goals, and *every customer turn* | **The rep's turns** — what your agent says back to the customer |
| **The scenario** — the task, its setup, and the success criteria | **The tools** — what it calls to navigate and mutate the world (names, validation, granularity are all yours) |
| **The physics** — the deterministic rating engine (`rate()`) and other canonical calculations | **The writes** — the actual SQL/mutations it issues against the world |
| **The grading** — the two gates (changeset DB-diff + LLM judge) and `pass^k` | **The model & prompts** — which LLM, system prompt, examples, anything |
| **The interface** — the environment service (`query`/`write`/`rate`/`search_kb`) and the agent contract | **The stack** — any language, any framework, any runtime |

Your agent only ever sees the **environment service** the bench injects per
session — it never holds the database, never sees the persona's hidden state, and
never produces a customer turn. As long as it speaks the agent contract (see
`docs/08`), the bench can drive it.

**Write your own evals, too.** The same world + environment service is reusable
outside the bench's grading — point your own harness or experiments at it. The
bench's grading is just *one* opinionated way to score against this world.

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

## Quickstart

Uses [uv](https://docs.astral.sh/uv/). Build the world once, then run a task
against an agent implementation:

```bash
uv sync
python src/peico/build_reference.py && python src/peico/generate.py   # build out/peico.sqlite
```

The harness drives **any** agent that exposes a factory `(Environment) -> AgentClient`;
the reference agent lives in [`peico-reference-agent`](../peico-reference-agent).
Run the eval from a venv that has both packages (the reference agent installs the
bench, so run it from there):

```bash
cd ../peico-reference-agent
uv run peico-eval update_contact_email --agent peico_agent.adapter:make_agent -v
```

The bench owns the world, the environment service (`query`/`write`/`rate`/
`search_kb`), the customer simulator, and grading; the agent owns its tools, loop,
model, and prompts. See `docs/07` and `docs/08` for the contract.

## Roadmap

- **v1 — The Dataset (done).** A complete, internally-consistent, deterministic
  world: schema, all residential product lines, a deterministic rating engine,
  generated data, and the policy/knowledge-base documents.
- **v2 — The Harness (in progress).** Environment-as-a-service interface, the
  bench-owned user simulator, per-session DB isolation, two-gate scoring. The
  first end-to-end task (`update_contact_email`) runs green against the reference
  agent; more tasks and the wire/HTTP transport come next.
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
| Scoring model | Two gates: changeset DB-diff (transactional tasks) + LLM-judge (every task) |
| Access model | Environment-as-a-service: raw `query`/`write` SQL + `rate()`; grade outcomes, not tool calls |
| Build order | Docs → schema → generators → harness |

## Repo layout

```
docs/
  00-design-principles.md   The non-negotiable rules (determinism, checkability)
  01-world-model.md         PEICO: product lines, tiers, regions, promos, loyalty, risk, BI
  02-data-model.md          Relational schema
  03-rating-engine.md       Deterministic pricing — the load-bearing piece
  04-data-generation.md     How the dataset is built (code for numbers, AI for flavor)
  05-benchmark-design.md    Tasks, two-gate scoring, simulator, leaderboard
  06-lore-and-quirks.md     The catalog of legacy quirks (each mapped to a doc/tool)
  07-interface-and-access.md  Environment-as-a-service access model (raw SQL + rate(), grade outcomes)
  08-agent-interface-and-harness-spec.md  The authoritative bench↔agent contract
src/peico/
  build_reference.py, generate.py, rating.py, schema*.sql   The world + physics
  harness/                  World, environment service, simulator, grading, runner
tasks/                      Task definitions (persona + setup + checks)
```
