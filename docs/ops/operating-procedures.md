# Operating core: procedures

Everything below runs with `arbitrage-ops` (installed by `pip install -e .`). `--mode simulated` uses
`mandate.simulated.toml` and the simulated adapters; the default is live, which uses `mandate.toml` and, until live
adapters exist, can only report. Set `OPS_DATABASE_URL` (default `sqlite:///data/ops.db`; production is
`postgresql://...`).

## Setting up

```bash
pip install -e ".[dev]"          # or ".[postgres]" for psycopg only
arbitrage-ops migrate            # tables, charters, registry (if integrations/registry.toml exists), schedules
arbitrage-ops mandate            # exit 1 while any field is pending
```

## The demo (no real money)

```bash
arbitrage-ops --mode simulated migrate
arbitrage-ops --mode simulated demo
```

Buys 10 units from the simulated supplier, sells one through the simulated channel and processor, ships it with the
simulated carrier, settles, closes the return window and prints the simulated dashboard. Every row it writes has
`mode = simulated`; the live dashboard stays at zero.

## Filling the mandate

Edit `mandate.toml`, replacing each `"pending"` with the real value, and commit it. The core reads the file at start;
its fingerprint is written into every audit record so a later change is visible. `arbitrage-ops mandate` lists what
is still pending. Live actions stay impossible until the mandate is complete **and** an integration is marked live and
connected in the registry **and** the core has verified a real operation on it.

## Pausing and resuming

```bash
arbitrage-ops pause --scope purchasing --reason "owner review"   # new commitments stop; paid orders still ship
arbitrage-ops pause --scope all --reason "incident"              # everything stops
arbitrage-ops status                                             # shows active pauses and their ids
arbitrage-ops resume <pause_id>
```

Automatic pauses (failed reconciliation, daily spend or exposure limit reached, cash below reserve, unreliable
integration, cumulative loss exceeded) appear in `status` with `kind = automatic`; they never lift themselves.

## Running the worker

```bash
arbitrage-ops worker --once      # tick schedules, run due workflow steps, expire overdue agent runs
```

Run it from cron or the docker-compose `worker` service every minute. The core does not run continuously by itself;
without a scheduler it does nothing.

## Reconciling an ambiguous payment

An action in `payment_unknown` appears under exceptions in `status`. Resolve it through `Purchasing.reconcile(action_id)`
(the `reconcile_unknown_payments` workflow does this hourly): the core asks the counterparty what happened to the
transaction id it sent and moves the action to `ordered`, `paid` or `failed`. A retry of `place` on such an action is
refused.

## Reading the numbers

```bash
arbitrage-ops status             # one mode, human readable
arbitrage-ops status --json      # the dashboard document (docs/ops/dashboard-api.md)
arbitrage-ops readiness          # built / pending / blocked
arbitrage-ops audit              # verify the hash chain
```

## Testing

```bash
pytest                                                                    # SQLite only
OPSCORE_TEST_DATABASE_URL=postgresql://user@host:5432/opstest pytest      # each ops test again on PostgreSQL
```

The PostgreSQL database named is dropped and recreated by the fixtures; never point it at production.
