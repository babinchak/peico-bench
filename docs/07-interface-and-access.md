# 07 — Interface & Access Model

How the system-under-test (the agent) touches the world. The governing insight:
**reads and writes have opposite answers.** Writes must be locked behind
rule-enforcing tools; reads should be wide open over the raw database and wiki.
This split is what keeps scoring honest *and* makes "navigate a horrible legacy
system" the actual skill under test.

> Not built in v1 (dataset only). Recorded here so the dataset is shaped to
> support it: rules live as inspectable data, the wiki is a real table, and the
> rating engine is a pure module callable as a tool.

## The split, in one table

| | Mechanism | Why |
|---|---|---|
| **Writes** | Rule-enforcing tools only. **No raw SQL writes, ever.** | A DB diff is the score; raw `UPDATE` lets the agent satisfy the diff without doing the work (reverse-engineer the target row). Tools enforce eligibility/suitability/dependencies and write coupled rows (ledger + balance) atomically. |
| **Reads** | Read-only SQL + wiki/KB doc tools + engine query tools. | Reads are pure (no cheating risk). Navigating the gnarly schema *is* the skill. Hand-authoring a read tool per access pattern would sand off the difficulty and cap task design. |

## Three read modalities (mirror a real rep's desk)

1. **Structured data — `query_db`.** A read-only SQL surface over the per-task
   snapshot. Sandbox: read-only connection, statement timeout, no PRAGMA/ATTACH,
   `SELECT`-only parser guard. The agent joins, filters, and discovers data the
   way a rep navigates EVERGREEN. The dual-ID reconciliation, cryptic coverage
   codes, and grandfathered tiers only test anything if the agent has to *find*
   them here.
2. **Unstructured wiki — `search_kb` / `get_doc`.** Retrieval over
   `kb_documents` (underwriting guides, compliance notes, howtos, the glossary
   decoding `UM/UIM`, etc.). This is the policy wiki.
3. **Rules engine — `quote` / `check_eligibility`.** Pure functions that *run*
   the declarative rules and hand back the answer (premium + breakdown,
   allow/deny + reason). Realistic: reps have a quoting tool. Difficulty moves off
   the arithmetic and onto fact-gathering and judgment, which is what we want to
   measure.

A strong agent fluidly mixes all three: SQL to find the customer's vehicles, the
wiki to learn FL's hurricane-deductible rule, `quote` to price it.

## Write tools (rule-enforcing)

`bind_policy`, `endorse_policy`, `change_tier`, `apply_promo`, `cancel_policy`,
`reinstate_policy`, `create_bundle` / `break_bundle`, `record_suitability`,
`redeem_loyalty`, `open_fnol`, `update_contact`.

Each one:
- enforces the world's rules (eligibility, suitability gate, umbrella dependency,
  fraud hold) and returns a **structured error** when violated — a bad agent
  *can* attempt a wrong write; the attempt/outcome is what the diff records;
- writes coupled state together (e.g., `redeem_loyalty` writes the ledger entry,
  updates the balance cache, and applies the deductible credit in one unit);
- recomputes premium through the rating engine — never accepts a premium as input.

## Rules-as-data: one source, three consumers

The declarative rule rows (`eligibility_rules`, `discounts.stack_order`,
`promotions.stacks_with`/`caps`/`retired_rider`, tier sellability) are authored
**once** and read by three different consumers:

```
                 ┌───────────────────────────────┐
   rule rows ───>│ rating/eligibility engine      │  (quote, check_eligibility)
   (eligibility, ├───────────────────────────────┤
    discounts,   │ the agent, via query_db        │  (SELECT the rule, reason from it)
    promos,      ├───────────────────────────────┤
    tiers)       │ the website DB visualizer      │  (render the rule expression)
                 └───────────────────────────────┘
```

This is why the engine and the database never disagree, and why a task can ask
the agent to *explain a rule* (read the row) as well as *obey it* (call the
engine). Pricing **curves** stay as opaque `rate_tables.payload` behind `quote`;
it's the eligibility/discount/promo **logic** that ships as inspectable rows.

## Difficulty axis: tool availability

The same task + same checker runs at two ceilings:

- **Easy mode** — engine tools (`quote`, `check_eligibility`) available; the agent
  delegates the computation.
- **Hard mode** — engine tools withheld; the agent must `SELECT` the rule rows +
  read the wiki and compute eligibility/price itself, then make the write.

This separates strong models from weak ones without authoring new content.

## Deferred (not v1, not v2-blocking)
- **Authorization / query firewall.** v1–v2 give the agent broad read as a rep.
  Things a real rep shouldn't freely see (other customers' PII, `bi_signals`,
  `fraud_flag`) get gated later via **scoped read-only views** when privacy/fraud
  tasks are written. Don't build the firewall now — just don't depend on its
  absence.

## How this positions peico-bench
τ-bench measures "call the right tools." peico-bench adds a second axis: **operate
a gnarly relational database + policy wiki + declarative rules engine the way a
competent rep does.** The open SQL read surface over a deliberately legacy schema
is the differentiator — keep the database central, not a hidden backend.
