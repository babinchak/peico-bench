# 07 — Interface & Access Model

How the system-under-test touches the world. PEICO is an **open benchmark**: many
independent agent implementations compete, in any language, each bringing its own
tools, loop, model, and prompts. So the bench deliberately does **not** define a
tool API. It defines an **environment as a service** and grades **outcomes**, not
process. The exact wire contract (session lifecycle, payload shapes) is specified in
`08-agent-interface-and-harness-spec.md`; this doc is the access *model* and the
reasoning behind it.

> Not built in v1 (dataset only). Recorded here so the dataset is shaped to support
> it: rules live as inspectable data, the wiki is a real table, and the rating
> engine is a pure module callable as a service.

## The shape: environment as a service

The bench hosts the world; the agent consumes it. The agent **never holds the
database** — it issues calls against a per-session, isolated copy that the bench
provisions and grades:

| Primitive | Purpose |
|---|---|
| `query(sql)` | Read-only SQL over the session world. Wide open. |
| `write(sql)` | Mutate the session DB. The bench applies it and returns the resulting changeset as feedback. |
| `rate(facts, as_of)` (+ friends) | The canonical physics, exposed so every implementation prices identically. Documented so an agent may self-host them instead. |

The agent composes these into whatever named tools it likes (`update_contact`,
`bind_policy`, …). The bench grades the cumulative seed→final changeset and the
conversation — **never the agent's tool calls** (every implementation's tools
differ, so asserting on them is meaningless).

## Why raw SQL is allowed on both reads and writes

An earlier draft locked writes behind rule-enforcing tools and banned raw `UPDATE`,
fearing that "raw writes let the agent satisfy the diff without doing the work." That
fear mostly dissolves, and locking the write path is incompatible with letting agents
own their tools. The reversal rests on three things:

- **Knowing the correct changeset *is* the work.** To write the right premium you
  must compute it via `rate()`; to land the right rows you must reason about the
  rules. Raw SQL doesn't make the target easier to *know* — only easier to *apply*.
- **Rules are enforced by the expected outcome, not the write path.** An ineligible
  request's correct end-state is *no change* (+ a refusal); an agent that writes the
  illegal row fails the changeset. Negative space (Principle 7) still works.
- **Two gates bound cheating:** the changeset (right outcome) and the LLM-judge
  (legitimate, coherent, responsive conversation), with the bench owning the customer
  so the dialogue can't be fabricated.

The cost of the reversal is an authoring discipline, not a security hole: every
expected changeset must fully encode the rule-correct outcome — which Principle 3
(every assertable fact is a real column) is what makes possible.

## Three read modalities (mirror a real rep's desk)

A strong agent fluidly mixes all three; the bench provides the raw surface and a few
optional helpers.

1. **Structured data — `query(sql)`.** A read-only SQL surface over the session
   snapshot (read-only connection, statement timeout, no PRAGMA/ATTACH, `SELECT`-only
   guard). Joining, filtering, and *finding* the dual-ID reconciliation, cryptic
   coverage codes, and grandfathered tiers is the skill.
2. **The wiki — the `kb_documents` table.** Underwriting guides, compliance notes,
   howtos, the glossary decoding `UM/UIM`. Queryable directly via `query`; the bench
   may also expose a `search_kb(query)` convenience as an optional utility.
3. **The physics — `rate()` (+ eligibility helpers).** Pure functions that *run* the
   declarative rules and return the answer (premium + breakdown; allow/deny + reason).
   Realistic — reps have a quoting tool — and it moves difficulty off the arithmetic
   and onto fact-gathering and judgment.

## Difficulty axis: which utilities the bench exposes

Same task, same checker, two ceilings:

- **Easy mode** — the physics helpers (`rate`, eligibility) are exposed; the agent
  delegates the computation.
- **Hard mode** — they're withheld; the agent must `query` the `rate_tables` /
  `eligibility_rules` rows + read the wiki and compute price/eligibility itself before
  writing.

Separates strong models from weak ones without authoring new content. (`query` and
`write` are always available; only the physics *helpers* toggle.)

## Rules-as-data: one source, three consumers

The declarative rule rows (`eligibility_rules`, `discounts.stack_order`,
`promotions.*`, tier sellability) are authored **once** and read by three consumers:

```
                 ┌───────────────────────────────┐
   rule rows ───>│ the physics service           │  the bench's canonical engine
   (eligibility, │   (rate, eligibility helpers)  │  behind rate()
    discounts,   ├───────────────────────────────┤
    promos,      │ the agent, via query(sql)      │  SELECT the rule, reason from it
    tiers)       ├───────────────────────────────┤
                 │ the website DB visualizer      │  render the rule expression
                 └───────────────────────────────┘
```

This is why the engine and the database never disagree, and why a task can ask the
agent to *explain* a rule (read the row) as well as *obey* it (call `rate`). Pricing
**curves** stay opaque in `rate_tables.payload` behind `rate()`; it's the
eligibility/discount/promo **logic** that ships as inspectable rows.

## Honesty (see also 08)

- **The bench owns and powers the customer simulator** — the keystone. Turn-by-turn
  customer messages can't be fabricated by the agent.
- **Grading data never enters the world DB.** `query` exposes the world, never the
  task's success criteria or the customer's hidden goal.
- **The official customer (and judge) models are pinned** so leaderboard runs are
  apples-to-apples; local runs with your own key are unofficial.

## Deferred (not v1, not v2-blocking)
- **Authorization / query firewall.** v1–v2 give the agent broad read as a rep.
  Things a real rep shouldn't freely see (other customers' PII, `bi_signals`,
  `fraud_flag`) get gated later via scoped read-only views when privacy/fraud tasks
  are written. Don't build the firewall now — just don't depend on its absence.

## How this positions peico-bench
τ-bench measures "call the right tools." peico-bench drops the fixed tool API
entirely and measures something harder and more open: **can your agent — built any
way you like — operate a gnarly relational database + policy wiki + declarative rules
engine the way a competent rep does, and reach the right outcome through an honest
conversation?** The open SQL surface over a deliberately legacy schema is the
differentiator — keep the database central, not a hidden backend.
