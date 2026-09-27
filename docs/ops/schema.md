# Operating core: schema

Source of truth: `src/arbitrage/ops/schema.sql` (applied by `Database.migrate()`). Conventions: money is integer KRW
unless a `currency` column says otherwise; timestamps are ISO-8601 text in UTC; JSON is stored as text; every table
that holds money or state has `mode` (`simulated` | `live`).

| Table | Purpose | Keys and constraints |
|---|---|---|
| `locks` | One row per named lock (`budget`, `schedule:*`) | `name` PK |
| `accounts` | Chart of accounts (codes 1000–6300) | `code` PK |
| `journal_entries` | One balanced posting per economic event | `event_key` UNIQUE (idempotent replay), `mode` |
| `journal_lines` | Debit/credit lines of an entry | `entry_id` → `journal_entries`, `account` → `accounts` |
| `inventory_lots` | FIFO lots at landed unit cost | `sku`, `mode`, `remaining` |
| `orders` | Customer orders | UNIQUE (`channel`, `external_order_id`, `mode`); `import_mode` NOT NULL; `customs_code_provided` 0/1, never the code itself |
| `actions` | Every controlled action (payment, purchase, spend, fulfillment, listing) | `idempotency_key` UNIQUE, `request_fingerprint`, `state`, `reservation_id` |
| `action_transitions` | State history per action | `action_id`, `from_state`, `to_state`, `confirmation_id` |
| `external_confirmations` | Evidence from the counterparty for money or goods moving | UNIQUE (`source`, `kind`, `external_reference`) |
| `budget_reservations` | Atomic holds on headroom | `state` reserved/committed/released, `source` initial_capital/reinvestment, `purpose`, `sku` |
| `pauses` | Owner and automatic pauses | `scope` purchasing/all, `kind` owner/automatic, `condition`, `lifted_at` |
| `integrations` | Registry rows loaded from `integrations/registry.toml` (schema owned by the platform-eligibility task) plus runtime facts (`health`, `verified_at`, `verification_reference`, `last_reconciled_at`) | `id` PK |
| `reconciliations` | Each reconciliation run and its difference | `integration`, `kind`, `status` |
| `agent_charters` | Charters as loaded, versioned | `role` PK |
| `tasks` | Orchestrator tasks | `fingerprint` UNIQUE, `parent_id`, `depends_on`, `state`, `attempts`, `not_before` |
| `agent_runs` | One claim of a task by a worker | `task_id`, `role`, `worker`, `credits_used`, `deadline_at` |
| `workflows` | Durable workflow instances | `dedupe_key` UNIQUE, `step`, `payload`, `attempts`, `locked_by`, `locked_until` |
| `workflow_events` | Step log per workflow | `workflow_id`, `at` (microseconds) |
| `schedules` | Recurring starts | `name` PK, `interval_seconds`, `last_slot` |
| `evidence` | Files the decisions cite (quotes, screenshots, certificates), by hash | `sha256`, `record_type`, `record_id` |
| `audit_log` | Hash-chained record of every authorization or money change | `seq` BIGSERIAL, `prev_hash`, `hash`, `mandate_fingerprint` |

## Chart of accounts

Assets 1000 Cash, 1100 Payment receivables, 1200 Inventory, 1300 Prepaid suppliers. Liabilities 2000 Supplier payables,
2200 Dispute provision, 2300 Returns provision, 2400 Tax payable, 2500 Accrued marketplace fees. Equity 3000 Capital.
Revenue 4000 Gross sales, 4100 Discounts, 4200 Refunds. Cost of sales and variable costs 5000 COGS, 5100 Freight,
5200 Duties and non-recoverable taxes, 5300 Marketplace fees, 5310 Payment processing fees, 5400 Currency conversion,
5500 Advertising, 5600 Return handling, 5610 Defects and write-offs, 5620 Chargebacks, 5700 Variable operating costs,
5720 Samples, 5800/5810 Provision expenses. Fixed costs 6000 Software, 6100 AI credits, 6200 Infrastructure, 6300 Other.

## Profit definitions (from `ops/metrics.py`)

- Net revenue = gross sales − discounts − refunds.
- Contribution profit = net revenue − COGS − variable costs.
- Operating profit = contribution profit − fixed costs.
- Realized profit = operating profit on orders that are settled **and** past the return window, net of fees, FX and
  reserves. This is the only figure compared with the KRW 1,000,000 target, and only in live mode.
- Provisional profit = operating profit − realized profit.
