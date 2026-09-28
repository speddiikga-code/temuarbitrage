-- GlobalCompute Router tables, applied by Database.migrate() after the core schema (same conventions: TEXT/INTEGER/
-- BIGINT only, ISO-8601 UTC text timestamps, JSON as text, money as integer KRW, rates as basis points, booleans 0/1,
-- every business row carries `mode`). Prices are integer micro-units of the price currency per million tokens.

CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  billing_mode TEXT NOT NULL,          -- own_keys | platform_credits
  processor TEXT,                      -- billing processor integration (simulated:billing until a real one is verified)
  vat_rate_bp INTEGER NOT NULL,        -- VAT on our charge, basis points (1000 = 10%); 0 needs a stated basis
  vat_basis TEXT,
  region TEXT NOT NULL,
  provider_credentials TEXT NOT NULL DEFAULT '[]',  -- [{provider, credential_ref}]: environment-variable names, never values
  cache_scope TEXT NOT NULL DEFAULT 'customer',     -- customer (only this customer's results) | shared
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_catalog (
  id TEXT PRIMARY KEY,                 -- provider:model:region
  provider TEXT NOT NULL,              -- integration id from the registry, or simulated:<name>
  model TEXT NOT NULL,
  region TEXT NOT NULL,
  tier INTEGER NOT NULL DEFAULT 0,     -- 0 smallest; the escalation ladder climbs by quality, tiers order decomposition
  task_types TEXT NOT NULL DEFAULT '[]',
  context_window INTEGER NOT NULL,
  input_micros_per_mtok BIGINT NOT NULL,   -- price per 1M input tokens in millionths of `currency` (USD 3.00 = 3000000)
  output_micros_per_mtok BIGINT NOT NULL,
  currency TEXT NOT NULL,
  latency_ms INTEGER NOT NULL,             -- expected latency of a typical call
  quality TEXT NOT NULL DEFAULT '{}',      -- {task_type: 0..1} seeded from evidence, then learned from judge verdicts
  quality_samples TEXT NOT NULL DEFAULT '{}',
  available INTEGER NOT NULL DEFAULT 1,
  terms_permit INTEGER NOT NULL DEFAULT 0, -- the provider's terms allow routing customer work through it (eligibility work)
  evidence TEXT NOT NULL DEFAULT '{}',     -- {source, url, date, verified}: where the price came from; unverified until sourced
  updated_at TEXT NOT NULL,
  mode TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_model_catalog_mode ON model_catalog (mode, available);

CREATE TABLE IF NOT EXISTS routed_requests (
  id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  customer_id TEXT NOT NULL REFERENCES customers (id),
  billing_mode TEXT NOT NULL,
  task_type TEXT NOT NULL,
  optimization TEXT NOT NULL,          -- economy | balanced | maximum
  quality_min_bp INTEGER NOT NULL,
  latency_max_ms INTEGER,
  cost_cap_krw BIGINT NOT NULL,        -- the customer's cap on provider cost for this request
  language TEXT NOT NULL,              -- answer language
  prompt TEXT NOT NULL,
  context TEXT NOT NULL DEFAULT '',
  compressed_context TEXT,
  max_output_tokens INTEGER NOT NULL,
  baseline_catalog_id TEXT,            -- the route the customer would have used; savings are measured against it
  metadata TEXT NOT NULL DEFAULT '{}',
  intent TEXT NOT NULL DEFAULT '{}',
  input_tokens_raw INTEGER NOT NULL DEFAULT 0,
  input_tokens_sent INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  plan TEXT NOT NULL DEFAULT '{}',
  step TEXT NOT NULL,                  -- received | compiled | planned | executing | judged | billed | delivered | failed
  status TEXT NOT NULL,                -- open | delivered | invoiced | settled | closed | failed | refunded | chargeback | cancelled
  cache_hit INTEGER NOT NULL DEFAULT 0,
  cached_from TEXT,
  provider_cost_krw BIGINT NOT NULL DEFAULT 0,   -- what the provider charged for the delivered result
  attempts_cost_krw BIGINT NOT NULL DEFAULT 0,   -- provider cost of every attempt, failed ones included
  baseline_cost_krw BIGINT NOT NULL DEFAULT 0,   -- what the customer's baseline route would have cost (estimate)
  savings_krw BIGINT NOT NULL DEFAULT 0,
  savings_verified INTEGER NOT NULL DEFAULT 0,   -- 1 only when both prices carry verified evidence
  charge_krw BIGINT NOT NULL DEFAULT 0,          -- what the customer is billed, VAT included
  fee_krw BIGINT NOT NULL DEFAULT 0,             -- the platform's fee inside the charge
  tax_krw BIGINT NOT NULL DEFAULT 0,
  quality_score_bp INTEGER,
  judge TEXT NOT NULL DEFAULT '{}',
  payment_id TEXT,                     -- customer_payment action for an own_keys invoice
  result TEXT,                         -- the delivered output
  dispute_window_ends TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  mode TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_routed_requests_customer ON routed_requests (customer_id, mode);
CREATE INDEX IF NOT EXISTS ix_routed_requests_status ON routed_requests (mode, status);

CREATE TABLE IF NOT EXISTS route_executions (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL REFERENCES routed_requests (id),
  attempt INTEGER NOT NULL,
  stage TEXT NOT NULL,                 -- full | preprocess | residual | escalation
  catalog_id TEXT NOT NULL,
  action_id TEXT,                      -- the inference_call action in the gateway
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  cost_krw BIGINT NOT NULL DEFAULT 0,
  funding TEXT NOT NULL DEFAULT 'none',   -- customer_key | prepaid | payable | none (failed before any call)
  fx_rate TEXT,
  latency_ms INTEGER,
  quality_score_bp INTEGER,
  passed INTEGER,
  provider_reference TEXT,
  output TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_route_executions_request ON route_executions (request_id, attempt);

CREATE TABLE IF NOT EXISTS route_cache (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,                 -- a customer id, or 'shared'
  task_type TEXT NOT NULL,
  language TEXT NOT NULL,
  fingerprint TEXT NOT NULL,           -- sha256 of the normalized prompt and context
  tokens TEXT NOT NULL DEFAULT '[]',   -- normalized word set, for near-duplicate detection
  request_id TEXT NOT NULL,
  result TEXT NOT NULL,
  quality_score_bp INTEGER NOT NULL,
  hits INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  UNIQUE (scope, task_type, language, fingerprint, mode)
);
CREATE INDEX IF NOT EXISTS ix_route_cache_scope ON route_cache (mode, scope, task_type, language);
