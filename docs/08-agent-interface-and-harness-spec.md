# 08 — Agent Interface & Harness Spec

The authoritative contract between the benchmark and an agent implementation, and how
the harness runs and grades a task. `07-interface-and-access.md` gives the access
*model* and its rationale; this doc is the *spec*.

> Not built in v1 (dataset only). This is the target the dataset and (v2) harness are
> built to satisfy.

## Roles

- **Bench** — hosts the per-session world, **owns and powers the customer simulator**,
  exposes the environment service (`query`/`write`/`rate`), drives the conversation,
  and grades. Owns everything the agent must not see (tasks, expected outcomes, the
  customer's hidden goal).
- **Agent implementation** — any program, any language, with its own tools, loop,
  model, and prompts. Produces rep turns; calls the environment service for data.
  peico-reference-agent is the canonical example, not a privileged one.

## Call directions

```
  Bench ──> Agent      start(session) -> welcome ; turn(customer_msg) -> reply(+terminate?)
  Agent ──> Bench-env  query(sql) ; write(sql) ; rate(facts, as_of) ; search_kb(q)
  Bench (internal)     customer simulator between agent turns ; grading after end
```

The agent and the environment service call *each other* during a run; both are scoped
to one `session_id`. There is no static code dependency in either direction — locally
it's object injection, remotely it's two services.

## Session lifecycle

1. **Provision.** Bench copies the seed DB → a private session file, applies the
   task's `setup` SQL, snapshots the **baseline**.
2. **`start`** (bench → agent): a new session begins; the agent returns its
   **welcome** message (the rep speaks first).
3. **Conversation loop**, up to `max_turns`:
   a. The customer simulator (bench) produces the next customer message, reacting to
      the last rep message + its persona.
   b. **`turn`** (bench → agent): the customer message; the agent runs its own
      internal loop — making any number of `query`/`write`/`rate` calls — and returns
      its reply plus an optional `terminate` flag.
   c. If `terminate`, stop.
4. **Termination.** The agent ends voluntarily via `terminate` (its closing/thanks
   turn — the rep also speaks last). The bench enforces `max_turns` as a hard cap;
   hitting it without `terminate` marks the session **incomplete**.
5. **`end`** (bench → agent): cleanup. Bench snapshots the **final** state and grades.

## Wire contract (transport-agnostic JSON)

Bench → Agent:

```jsonc
// start
{ "session_id": "S1",
  "world": { "anchor_date": "2025-06-01",
             "capabilities": ["query","write","rate","search_kb"] } }
// -> agent
{ "message": "Hi, welcome to PEICO — how can I help today?",
  "trace": [/* opaque, optional, display-only */] }

// turn
{ "session_id": "S1", "customer_message": "I want to update my email." }
// -> agent
{ "message": "Sure — can I get your name or account number?",
  "terminate": false, "trace": [/* optional */] }
```

Agent → Bench-env (each scoped by `session_id`):

```jsonc
// query (read-only)
{ "session_id": "S1",
  "sql": "SELECT cust_id,email FROM customers WHERE last_name='Pennington'" }
// -> { "rows":[...], "row_count":1, "truncated":false }
//  | { "error":"sql_error", "detail":"..." }

// write (mutate session copy; returns the resulting changeset)
{ "session_id": "S1",
  "sql": "UPDATE customers SET email='x@y.com' WHERE cust_id='CUST-...'" }
// -> { "ok":true, "changeset": { "customers": { "changed":[ ... ] } } }
//  | { "error":"...", "detail":"..." }

// rate (canonical physics)
{ "session_id": "S1", "facts": { "line":"AUTO", "...":"..." }, "as_of":"2025-06-01" }
// -> { "base_premium_cents":..., "final_premium_cents":..., "breakdown":[...] }
//  | { "error":"..." }

// search_kb (optional read helper; or just query the kb_documents table)
{ "session_id": "S1", "query":"umbrella underlying", "limit":8 }
// -> { "results":[ { "doc_id":"...", "title":"...", "snippet":"..." } ] }
```

Errors are **structured, not fatal** — the agent reads them and recovers (recovering
from a structured rejection is part of the skill). An agent that crashes, times out,
or never terminates fails the session.

## Task definition (bench-side; never sent to the agent)

```yaml
task_id: update-contact-email
persona:
  name: Walter Pennington
  profile: >          # hidden context that shapes behavior, not stated outright
    Long-time auto customer, late 60s, not technical.
  knowledge: |        # what the customer will say / reveal if relevant
    Wants email changed to walter.p@example.com; account EVG0098H1.
  reactions: |        # how to react to what the rep surfaces (incl. forgotten holdings)
    Once the rep confirms the change, thank them and you're done.
  goal: >             # the customer's success intent (drives the simulator, not the grader)
    Email on file updated.
setup: []             # SQL applied to the session copy before the run
max_turns: 8
checks:
  - type: judge       # EVERY task has at least a judge
    rubric: The rep confirmed the new email back to the customer.
  - type: changeset   # transactional tasks add an objective assertion
    expected:
      customers:
        changed:
          - pk: { cust_id: CUST-heritage-auto }
            fields: { email: ["walter.pennington@example.com", "walter.p@example.com"] }
```

## Grading

- **changeset** — `diff(baseline, final)` must equal `expected` (order-insensitive
  across rows; `[old,new]` deltas ordered). Captures both "right rows changed" and
  "nothing else did" in one comparison.
- **judge** — pinned model, temp 0, structured `{passed, reason}` over a binary
  rubric; judges correctness/regulatory + good-faith engagement. Majority-vote
  optional for official runs.
- **task verdict** — passes iff all *required* checks pass **and** the conversation
  completed. An **incomplete** conversation fails by default (checks still run, for
  diagnostics).
- **suite score** — fraction of tasks passed; report `pass@1` and `pass^k` over k
  customer-simulator seeds.

## Honesty model (see 07)

- The bench owns + powers the customer; turns can't be fabricated.
- The agent receives only what a rep would: customer messages + the environment. It
  never sees the task, the expected changeset, or the customer's hidden goal — and
  grading data is never stored in the world DB.
- The **official customer and judge models are pinned**; local runs with your own key
  are unofficial.

## Transport, staged

The contract above is transport-agnostic. Build behind an `AgentClient` seam:

- **Now (local):** in-process. The bench injects a session **environment handle** into
  the agent and calls its methods directly. Fast iteration in tandem with the
  reference agent.
- **Later (hosted):** the handle becomes an HTTP client to the bench's env API, and
  the agent becomes an HTTP service the bench calls (register an endpoint; the bench
  runs your agent). Same JSON, new wires.

## Out of scope
Token/cost/latency are **not** graded or transported — they're a property of an
agent+model, surfaced on the website for the reference agent, not part of the bench.
