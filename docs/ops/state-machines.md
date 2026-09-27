# Operating core: state machines

Defined in `src/arbitrage/ops/gateway.py`. A transition not listed is rejected with `InvalidTransition`. A transition
marked **(confirmation)** needs an `external_confirmations` row of the named kind from the counterparty, unique per
(source, kind, external reference); a duplicate reference is ignored, not posted twice. Every transition writes an
`action_transitions` row and an audit record.

## Customer payment (`customer_payment`)

```
created → authorized (authorization) | failed
authorized → captured (capture) | voided (void)
captured → settled (settlement) | partially_refunded (refund) | refunded (refund) | disputed (dispute_opened)
settled → partially_refunded | refunded | disputed
partially_refunded → partially_refunded | refunded | disputed
disputed → dispute_won (dispute_closed) | dispute_lost (dispute_closed)
dispute_won → partially_refunded | refunded
terminal: dispute_lost, refunded, voided, failed
```

Ledger effects: capture books receivable, gross sales, the expected fee accrual and the return/dispute provisions;
settlement moves receivable to cash and books the actual fees (payout + fees must equal the receivable); refund books
the contra-revenue and cash out; a lost dispute books a chargeback. Nothing is booked from an event without a reference.

## Supplier purchase (`supplier_purchase`, `sample_purchase`)

```
proposed → verified | rejected
verified → reserved | rejected
reserved → ordered (supplier_order) | payment_unknown | failed | cancelled
ordered → paid (payment_receipt) | payment_unknown | cancelled
payment_unknown → ordered | paid | failed          (only through reconcile(), never a retry)
paid → shipped (shipment) | refunded (supplier_refund)
shipped → received (receiving) | lost
terminal: received, rejected, failed, cancelled, refunded, lost
```

`verify` re-checks the proposal against a fresh supplier quote and the mandate: import basis (resale is never
personal use), duty evidence (unknown is never zero), category permission, price evidence (source, URL, date) and the
governor's limits. `reserve` takes headroom atomically. `place` calls the adapter with the action id as the
transaction id; an ambiguous result parks the action in `payment_unknown` and raises `ReconciliationRequired`.
`receive` books an inventory lot at landed cost (goods + freight + duties), or an expense for a sample.

## Spend (`advertising`, `software_expense`, `infrastructure_expense`, `reinvestment`)

```
proposed → reserved | rejected
reserved → paid (payment_receipt) | payment_unknown | failed | cancelled
payment_unknown → paid | failed
terminal: paid, rejected, failed, cancelled
```

## Fulfillment (`fulfillment`)

```
pending → allocated | cancelled
allocated → packed | cancelled
packed → shipped (shipment) | cancelled
shipped → delivered (delivery) | return_requested | lost
delivered → completed | return_requested
return_requested → returned (return_receipt) | completed
completed → return_requested                (goodwill returns after the window)
terminal: returned, cancelled, lost
```

`allocate` reserves FIFO stock; `ship` books COGS and outbound freight and passes the customer's 개인통관고유부호 to the
carrier for that shipment only (the core stores `customs_code_provided = 1`, never the code). `close_return_windows`
moves delivered orders to `completed` after the mandate's refund-reserve days and releases their provisions.

## Listing (`listing`)

```
proposed → verified | rejected
verified → listed (listing) | rejected
listed → delisted (delisting)
delisted → listed (listing)
terminal: rejected
```

`verify` requires per-SKU certification evidence and an import mode before a listing can be published.

## Orchestrator tasks and runs

```
task: queued → blocked (dependencies) → running → done | failed → queued (retry) | escalated
run:  running → done | failed | expired
```

Retries back off 60 s, 300 s, 900 s, then the task escalates to the owner. A run past its deadline expires and counts
as a failure.

## Workflows

```
pending → running → pending (wait) | done | failed
```

A step handler returns `proceed`, `wait(seconds)`, `done` or `fail`. A lease (`locked_by`, `locked_until`) protects a
running step; an expired lease is claimable by another worker.
