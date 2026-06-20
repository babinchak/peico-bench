<p align="center">
  <img src="assets/peico-mascot.png" alt="Sappy the Pinecone" height="150" align="middle">
  &nbsp;&nbsp;
  <img src="assets/peico-letters.png" alt="PEICO" height="64" align="middle">
</p>

# PEICO Insurance Agent Benchmark (`peico-bench`)

`peico-bench` measures how well an autonomous agent can act as a **sales and
service representative** for a fictional consumer insurance company, **PEICO**.
Your agent is dropped into a multi-turn conversation with a simulated customer,
given read/write access to a realistic insurance database, and scored on whether
it **reached the right outcome and changed the right data** — without mis-selling,
violating regulation, or touching records it shouldn't.

Bring your own agent, in any stack. The bench owns the world and the rules; you
own the player. The reference implementation lives in
[`peico-reference-agent`](https://github.com/babinchak/peico-reference-agent) — clone it to see a working
agent end-to-end, or use it as the template for your own.

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

## What makes it hard

PEICO ("**P**rotective **E**vergreen **I**nsurance **CO**mpany") runs on
**EVERGREEN**, a mainframe first written in 1987 and layered on by decades of
well-meaning people who never talked to each other: grandfathered tiers nobody
sells anymore, two customer-ID systems that don't reconcile, promo codes with
inconsistent rules, cryptic coverage abbreviations, and products that exist in
some states for purely historical licensing reasons. Your agent has to navigate
that and still do right by the customer. Specifically, it's scored on whether it
can:

- **Reach the right outcome, exactly.** A policy is either bound at the right tier
  with the right premium, or it isn't. Most scoring is a database diff, not a vibe
  check.
- **Know when *not* to act.** Suitability rules, mandatory disclosures,
  state-by-state eligibility, and risk-based declines mean the highest-scoring
  move is sometimes *to not make the sale*. The obvious action is often wrong.
- **Handle a customer who doesn't know what they need.** Customers misstate facts,
  omit risk factors, and have hidden budgets and goals. The stated goal is not
  always the optimal outcome.
- **Find the rules, not memorize them.** Every quirk lives in retrievable
  documentation or a queryable tool — never only in a test author's head. We
  measure *navigation*, not trivia.

> The lore is fun (mascot: **Sappy the Pinecone**; tagline: *"15 pinecones could
> save you 15%"*), but the mechanics are rigorous. The full quirk catalog is in
> [`docs/06`](docs/06-lore-and-quirks.md).

## How scoring works

Every task is graded on **outcomes, not process** — the bench never asserts on
which tools your agent called. Two gates:

- **Changeset (transactional tasks).** The cumulative seed→final database diff
  must equal the expected changeset. Right data, exactly.
- **LLM judge (every task).** A rubric judge checks correctness and good-faith
  engagement with the customer.

A task passes only if its required checks pass **and** the agent terminated the
conversation itself (running out of `max_turns` counts as incomplete). Repeated
trials roll up into **`pass^k`** (passed all *k* attempts). The full contract is
in [`docs/08`](docs/08-agent-interface-and-harness-spec.md).

## Benchmark your own agent

The bench drives **any** agent that implements a small contract: a factory
`(Environment) -> AgentClient`, where the client exposes `welcome()` (the rep
speaks first) and `respond(customer_message) -> reply`. Your agent reads and
writes the world only through the injected `Environment`
(`query`/`write`/`rate`/`search_kb`).

The contract is transport-agnostic. Today it runs **in-process** — the bench
imports your factory by path — with an HTTP transport (register a remote agent
endpoint) planned. The reference agent's
[`adapter.py`](https://github.com/babinchak/peico-reference-agent/blob/master/peico_agent/adapter.py) is the canonical
example; copy it as your starting point.

```bash
# from a venv that has both peico (this repo) and your agent installed:
peico-eval update_contact_email --agent your_module:make_agent -k 5 -v
```

## Quickstart

Uses [uv](https://docs.astral.sh/uv/). Build the world once, then run the
reference agent against it (the reference agent installs this bench, so the eval
runs from there):

```bash
# in peico-bench: build out/peico.sqlite once
uv sync
python src/peico/build_reference.py && python src/peico/generate.py

# in peico-reference-agent: run a task end-to-end
cd ../peico-reference-agent
uv run peico-eval update_contact_email --agent peico_agent.adapter:make_agent -v
```

## Status

- **v1 — The Dataset (done).** A complete, internally-consistent, deterministic
  world: schema, all residential product lines, a deterministic rating engine,
  generated data, and the policy/knowledge-base documents.
- **v2 — The Harness (in progress).** Environment-as-a-service interface, the
  bench-owned user simulator, per-session DB isolation, two-gate scoring. The
  first end-to-end task (`update_contact_email`) runs green against the reference
  agent; more tasks and the wire/HTTP transport come next.
- **v3 — The Tasks.** A dev split (public) and a held-out test split (private).
- **v4 — The Website.** Database visualizer + leaderboard (score and token/cost
  reported together), held-out verification.

### Results & leaderboard

*Coming soon (v4).* A public leaderboard with held-out verification is planned.
Until then, the reference agent is the live baseline — `update_contact_email`
currently runs `pass^1 = 1/1`.

## Docs

Deep dives live in [`docs/`](docs/):

| Doc | What's in it |
|---|---|
| [`00`](docs/00-design-principles.md) | Non-negotiable rules (determinism, checkability) |
| [`01`](docs/01-world-model.md) | PEICO: product lines, tiers, regions, promos, loyalty, risk |
| [`02`](docs/02-data-model.md) | Relational schema |
| [`03`](docs/03-rating-engine.md) | Deterministic pricing — the load-bearing piece |
| [`04`](docs/04-data-generation.md) | How the dataset is built (code for numbers, AI for flavor) |
| [`05`](docs/05-benchmark-design.md) | Tasks, two-gate scoring, simulator, leaderboard |
| [`06`](docs/06-lore-and-quirks.md) | The catalog of legacy quirks (each mapped to a doc/tool) |
| [`07`](docs/07-interface-and-access.md) | Environment-as-a-service access model |
| [`08`](docs/08-agent-interface-and-harness-spec.md) | The authoritative bench↔agent contract |

## Repo layout

```
docs/                       Design docs (table above)
src/peico/
  build_reference.py, generate.py, rating.py, schema*.sql   The world + physics
  harness/                  World, environment service, simulator, grading, runner
tasks/                      Task definitions (persona + setup + checks)
```

## Acknowledgments

Closely modeled on Sierra's **τ-bench / τ²-bench** (user simulator + tool API +
database end-state assertion). If you're contributing to the benchmark itself,
read those papers first — this project reuses their core architecture.
