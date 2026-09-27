-- Operating core schema. Portable between SQLite and PostgreSQL: TEXT/INTEGER/BIGINT only, ISO-8601 UTC
-- timestamps as TEXT, JSON as TEXT, money as integer KRW, booleans as 0/1. Every business row carries
-- `mode` = 'simulated' | 'live' so the two environments never mix. {{BIGSERIAL}} is replaced per dialect.

CREATE TABLE IF NOT EXISTS locks (
  name TEXT PRIMARY KEY
);

-- Ledger -------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS accounts (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,            -- asset | liability | equity | revenue | expense
  normal_side TEXT NOT NULL,     -- debit | credit
  category TEXT NOT NULL,        -- see ledger.CHART
  fixed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS journal_entries (
  id TEXT PRIMARY KEY,
  posted_at TEXT NOT NULL,
  event TEXT NOT NULL,
  description TEXT NOT NULL,
  reference_type TEXT,
  reference_id TEXT,
  event_key TEXT NOT NULL UNIQUE,  -- one posting per business event, however often the event is delivered
  mode TEXT NOT NULL,
  provisional INTEGER NOT NULL DEFAULT 0,
  metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_journal_entries_ref ON journal_entries (reference_type, reference_id);

CREATE TABLE IF NOT EXISTS journal_lines (
  id TEXT PRIMARY KEY,
  entry_id TEXT NOT NULL REFERENCES journal_entries (id),
  line_no INTEGER NOT NULL,
  account_code TEXT NOT NULL REFERENCES accounts (code),
  debit BIGINT NOT NULL DEFAULT 0,
  credit BIGINT NOT NULL DEFAULT 0,
  memo TEXT
);
CREATE INDEX IF NOT EXISTS ix_journal_lines_account ON journal_lines (account_code);
CREATE INDEX IF NOT EXISTS ix_journal_lines_entry ON journal_lines (entry_id);

-- Operations ---------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS inventory_lots (
  id TEXT PRIMARY KEY,
  sku TEXT NOT NULL,
  purchase_id TEXT,
  quantity INTEGER NOT NULL,
  remaining INTEGER NOT NULL,
  unit_cost BIGINT NOT NULL,      -- landed KRW per unit (goods + inbound freight + duties)
  received_at TEXT NOT NULL,
  mode TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_inventory_lots_sku ON inventory_lots (sku, mode);

CREATE TABLE IF NOT EXISTS orders (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  external_order_id TEXT NOT NULL,
  sku TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  gross_amount BIGINT NOT NULL,   -- what the customer pays before discount, VAT included
  discount BIGINT NOT NULL DEFAULT 0,
  tax_collected BIGINT NOT NULL DEFAULT 0,   -- VAT remitted to the authorities, never revenue
  expected_fee BIGINT NOT NULL DEFAULT 0,    -- marketplace fee accrued at capture, trued up at settlement
  currency TEXT NOT NULL DEFAULT 'KRW',
  import_mode TEXT NOT NULL,      -- commercial_resale | personal_use (구매대행) | genuine_sample; required, never defaulted
  customs_code_provided INTEGER NOT NULL DEFAULT 0,  -- 개인통관고유부호 was passed to the carrier; the code itself is never stored
  placed_at TEXT NOT NULL,
  status TEXT NOT NULL,           -- placed | paid | fulfilled | settled | closed | refunded | disputed
  return_window_ends TEXT,
  payment_id TEXT,
  fulfillment_id TEXT,
  mode TEXT NOT NULL,
  UNIQUE (channel, external_order_id, mode)
);

CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY,                       -- the unique transaction id sent to external systems
  idempotency_key TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,                        -- customer_payment | supplier_purchase | fulfillment | expense ...
  mode TEXT NOT NULL,
  state TEXT NOT NULL,
  amount BIGINT NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'KRW',
  amount_krw BIGINT NOT NULL DEFAULT 0,
  integration TEXT,
  reference_type TEXT,
  reference_id TEXT,
  reservation_id TEXT,
  sku TEXT,
  request_fingerprint TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_error TEXT
);
CREATE INDEX IF NOT EXISTS ix_actions_kind_state ON actions (kind, state, mode);

CREATE TABLE IF NOT EXISTS action_transitions (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL REFERENCES actions (id),
  from_state TEXT NOT NULL,
  to_state TEXT NOT NULL,
  at TEXT NOT NULL,
  confirmation_id TEXT,
  reason TEXT
);

CREATE TABLE IF NOT EXISTS external_confirmations (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL REFERENCES actions (id),
  source TEXT NOT NULL,            -- integration name; simulated adapters are 'simulated:<name>'
  kind TEXT NOT NULL,              -- authorization | capture | settlement | refund | dispute_opened | ...
  external_reference TEXT NOT NULL,
  amount BIGINT,
  currency TEXT,
  payload TEXT NOT NULL DEFAULT '{}',
  received_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  UNIQUE (source, kind, external_reference)
);

CREATE TABLE IF NOT EXISTS budget_reservations (
  id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  source TEXT NOT NULL,            -- initial_capital | reinvestment
  purpose TEXT NOT NULL,           -- inventory | sample | advertising | software | infrastructure | shipping ...
  amount BIGINT NOT NULL,
  committed_amount BIGINT,
  state TEXT NOT NULL,             -- reserved | committed | released
  action_id TEXT,
  workflow_id TEXT,
  sku TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  note TEXT
);
CREATE INDEX IF NOT EXISTS ix_budget_reservations_state ON budget_reservations (mode, state);

CREATE TABLE IF NOT EXISTS pauses (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,             -- purchasing (new commitments) | all
  kind TEXT NOT NULL,              -- owner | automatic
  condition TEXT,                  -- automatic pauses: which guardrail fired
  reason TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL,
  started_by TEXT NOT NULL,
  ended_at TEXT,
  ended_by TEXT
);

CREATE TABLE IF NOT EXISTS integrations (
  id TEXT PRIMARY KEY,               -- entry id from integrations/registry.toml, e.g. aliexpress_supplier
  name TEXT NOT NULL,
  mode TEXT NOT NULL,                -- live for every real platform; simulated entries back the simulated adapters
  roles TEXT NOT NULL DEFAULT '[]',
  verdict TEXT NOT NULL,             -- go | conditional | no_go | unknown
  status TEXT NOT NULL,              -- not_connected | credentials_pending | sandbox | live
  connected INTEGER NOT NULL DEFAULT 0,
  region_ok_for_korea INTEGER NOT NULL DEFAULT 0,
  eligibility TEXT,
  commercial_terms TEXT,
  integration TEXT,                  -- api | api_for_sellers | dashboard_only | none | ...
  credentials TEXT NOT NULL DEFAULT '[]',   -- environment variable names only, never values
  permissions TEXT,
  rate_limits TEXT,
  supported_operations TEXT NOT NULL DEFAULT '[]',
  manual_dependency TEXT,
  health TEXT NOT NULL DEFAULT 'unverified',
  last_verified TEXT,
  unknown_because TEXT,
  sources TEXT NOT NULL DEFAULT '[]',
  -- runtime facts recorded by the core, never by a file load
  verified_operation TEXT,
  verified_at TEXT,
  verification_reference TEXT,
  health_checked_at TEXT,
  last_reconciled_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliations (
  id TEXT PRIMARY KEY,
  integration TEXT NOT NULL,
  kind TEXT NOT NULL,              -- settlements | supplier_payments | orders | shipping | refunds
  status TEXT NOT NULL,            -- matched | mismatch | failed
  started_at TEXT NOT NULL,
  finished_at TEXT,
  our_total BIGINT,
  their_total BIGINT,
  difference BIGINT,
  detail TEXT NOT NULL DEFAULT '{}',
  mode TEXT NOT NULL
);

-- Agents and orchestration -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_charters (
  role TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  content TEXT NOT NULL,
  loaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  title TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  depends_on TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL,             -- queued | blocked | running | done | failed | escalated | cancelled
  priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  parent_run_id TEXT,
  depth INTEGER NOT NULL DEFAULT 0,
  run_id TEXT,
  result TEXT,
  error TEXT,
  not_before TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tasks_state ON tasks (state, priority);

CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks (id),
  role TEXT NOT NULL,
  parent_run_id TEXT,
  depth INTEGER NOT NULL,
  permissions TEXT NOT NULL DEFAULT '[]',
  credits_allowed INTEGER NOT NULL,
  credits_used INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL,             -- running | done | failed | expired
  worker TEXT,
  started_at TEXT NOT NULL,
  deadline_at TEXT NOT NULL,
  ended_at TEXT,
  outcome TEXT
);

-- Durable workflows ----------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  state TEXT NOT NULL,             -- pending | running | waiting | done | failed
  step TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  next_run_at TEXT,
  locked_by TEXT,
  locked_until TEXT,
  dedupe_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_error TEXT
);
CREATE INDEX IF NOT EXISTS ix_workflows_due ON workflows (state, next_run_at);

CREATE TABLE IF NOT EXISTS workflow_events (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES workflows (id),
  step TEXT NOT NULL,
  event TEXT NOT NULL,
  at TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS schedules (
  name TEXT PRIMARY KEY,
  workflow_type TEXT NOT NULL,
  interval_seconds INTEGER NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  next_run_at TEXT NOT NULL,
  last_started_at TEXT,
  enabled INTEGER NOT NULL DEFAULT 1
);

-- Evidence and audit ---------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,              -- invoice | receipt | screenshot | report | quote | photo
  uri TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  related_type TEXT,
  related_id TEXT,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  seq {{BIGSERIAL}},
  id TEXT NOT NULL UNIQUE,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  before TEXT,
  after TEXT,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL
);
