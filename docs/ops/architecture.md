# Operating core: architecture decisions

The operating core lives in `src/arbitrage/ops`. It is the part of the system that is allowed to touch money, stock and
external accounts, so its job is to refuse anything the owner has not authorized and to record everything it does.
Phase 1 (`arbitrage scan`) finds candidates; nothing in the scanner spends.

## What is built, and what is not

Built and tested (see [readiness.md](readiness.md) for the exact state): mandate loader that fails closed, double-entry
ledger, budget governor with atomic reservations, controlled action gateway with separate state machines, integration
registry loader, agent charters and a deterministic orchestrator, PostgreSQL/SQLite-backed durable workflows and
schedules, owner and automatic pauses, hash-chained audit trail, dashboard JSON, `arbitrage-ops` command.

Not built: any live adapter (AliExpress, Naver Smart Store, Coupang WING, a payment processor, a carrier). Every
adapter in the repository is a `Simulated*` class and says so in its name and in every row it produces. Nothing is
deployed and nothing runs continuously. The core has never held a real account, a real balance or a real order.

## Decisions

### 1. One package, stdlib first

The core is plain Python 3.11 with dataclasses and `sqlite3`, like the rest of `src/arbitrage`. PostgreSQL support is
an optional extra (`pip install -e ".[postgres]"`, psycopg 3). No ORM, no web framework: the dashboard is a function
that returns a dict, and the future API is a thin layer over that function ([dashboard-api.md](dashboard-api.md)).
Reason: the repo rule is "no framework in the core package", and every control here must be testable in a unit test
without a server.

### 2. Two databases, one SQL dialect

Tests run every case on SQLite and, when `OPSCORE_TEST_DATABASE_URL` is set, again on PostgreSQL. `ops/db.py` keeps the
SQL portable: `?` placeholders, TEXT/INTEGER/BIGINT only, ISO-8601 timestamps as text, JSON as text, money as integer
KRW, booleans as 0/1, `{{BIGSERIAL}}` for the audit sequence. Locks are one row per name in `locks`, taken with
`BEGIN IMMEDIATE` on SQLite and `SELECT ... FOR UPDATE` on PostgreSQL. Production is PostgreSQL; SQLite is for tests,
the demo and a single-operator laptop.

### 3. Fail-closed mandate

`mandate.toml` ships with every field set to the string `"pending"`. A pending numeric limit reads as zero, a pending
list as empty, so an incomplete mandate authorizes nothing: no external action kind, no category, no headroom. A
mandate whose `environment` is `simulated` can never authorize a live action, whatever its numbers. The mandate is a
file the owner edits and commits; the core never writes it. Its fingerprint is recorded on every decision.

### 4. Simulated and live are separate books

Every table that holds money or state has a `mode` column (`simulated` | `live`). Ledger balances, metrics, headroom,
reservations, confirmations and the dashboard are computed per mode. Only live realized profit counts toward the
KRW 1,000,000 target. A simulated adapter refuses to be used by a live action, and the demo refuses to run against a
live mandate.

### 5. Ledger is the source of truth; profit is settled cash

Every economic event is a balanced journal entry with a unique `event_key`, so replaying a processor webhook or a
supplier receipt posts nothing the second time. COGS is recognized at fulfillment from FIFO lots at landed cost.
Return and dispute provisions are booked at sale from the mandate's rates and released when the return window closes.
"Realized profit" is operating profit on orders that are settled and past the return window; everything else is
"provisional". Samples are expenses, never inventory.

### 6. Budget governor: reservations under one lock

Headroom = settled cash − unpaid commitments (payables, accrued fees, live reservations) − required reserves (minimum
cash, operating reserve, provisions, tax payable). Reinvestment budget = max(0, min(rate × (realized profit − already
allocated), headroom, remaining exposure)). A reservation takes the `budget` lock, re-reads every limit inside the
transaction and inserts or refuses; two workers racing for the last won cannot both win. Committed reinvestment
reservations count as allocated, so retained profit cannot be spent twice.

### 7. Action gateway: state machines plus external confirmation

Every action has a unique id and a caller-supplied idempotency key with a request fingerprint; the same key with a
different request is a conflict, not a retry. Customer payment, supplier purchase, spend, fulfillment and listing each
have their own state machine ([state-machines.md](state-machines.md)). A transition into a "money moved" or "goods
moved" state requires an `external_confirmations` row that is unique per (source, kind, external reference). An
adapter result that is neither confirmed nor failed parks the action in `payment_unknown`; the only way out is
reconciliation against the counterparty's records, never a blind retry.

### 8. Policy and pauses

The policy controller evaluates every action request against the mandate (environment, action kind, category,
transaction limit, integration production-readiness) and the active pauses. An owner pause with scope `purchasing`
blocks new commitments (purchases, samples, advertising, software, infrastructure, reinvestment, listings) while
customer payments, fulfillment, shipping and refunds continue; scope `all` blocks everything. Guardrails evaluate
the automatic conditions (failed reconciliation, daily spend or exposure limit reached, cash below reserve,
unreliable integration, cumulative loss exceeded) and open a purchasing pause that only the owner lifts.

### 9. Agents are data, the orchestrator is deterministic

`charters.toml` holds the thirteen charters. No charter carries an `execute:*` permission: agents propose and request,
the gateway executes, and the evaluator cannot propose. The orchestrator dedupes tasks by fingerprint, waits on
dependencies, caps concurrency per role, delegation depth, retries (60 s, 300 s, 900 s, then escalate) and credits per
run, per parent chain and against the mandate's AI-credit budget. A child task can hold only permissions its parent
holds. Nothing here calls a model; a worker that does would claim a task, do the work, and report completion.

### 10. Durable workflows in the database instead of Temporal

The owner's brief named Temporal for durable execution. This core uses a PostgreSQL-backed engine instead
(`ops/workflows.py`): a workflow is a row with a type, step, checkpoint payload, attempt count and a lease; a handler
returns `proceed`, `wait`, `done` or `fail`; a crashed worker's lease expires and another worker resumes the step;
schedules start one workflow per slot however many workers tick. Reasons: the stack must stay at one database plus one
Python process at this stage, the workflows are few and short, and every step is already idempotent through the
gateway. Swapping to Temporal later means implementing the same handler protocol as a Temporal workflow and pointing
`jobs.register_standard` at it; the ledger, gateway and policy do not change.

### 11. Audit trail

Every write that changes money or authorization is followed by an `audit_log` row (actor, action, entity, before,
after, mandate fingerprint) whose hash includes the previous row's hash. `arbitrage-ops audit` re-computes the chain.

### 12. Deployment target

`docker-compose.yml` describes the target: PostgreSQL 16, one worker container running `arbitrage-ops worker --once`
on a schedule, and the same image for one-off commands. It has not been run in this repository's development
environment (no Docker daemon there); see [readiness.md](readiness.md).
