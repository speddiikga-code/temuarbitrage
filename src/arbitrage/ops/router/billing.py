"""Layer 10, the money half: customer accounts, provider prepayments and the ledger entries of a routed request.

Two billing modes, both through the core's ledger and gateway:

* `own_keys`: the customer's provider keys pay the provider; the platform never spends and books no inference cost.
  The platform invoices a fee (a share of verified savings, or nothing when savings cannot be verified), as a
  `customer_payment` action whose processor confirmations book receivable, revenue, VAT, settlement and refunds.
* `platform_credits`: the customer prepays a balance (a liability until consumed) and the platform pays the
  provider from prepaid provider credits or on invoice.  A top-up becomes spendable only when the processor has
  *settled* it, so a request is ever charged from settled cash; each delivered request consumes the balance and
  books revenue, VAT and a dispute provision.

Every posting is idempotent through its event key, and nothing here moves without a confirmation: the gateway's
payment machine takes processor events, the provider's usage record confirms a call, and a receipt confirms a
prepayment.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .. import ledger as L
from ..audit import AuditTrail
from ..common import LIVE, iso, loads, new_id, now_iso, parse_iso, utcnow
from ..db import Database, Tx
from ..errors import InvalidTransition, OpsError
from ..gateway import Action, ActionGateway
from ..ledger import Entry, Ledger, cr, dr
from ..mandate import BILLING_MODES, Mandate
from ..policy import ActionRequest, PolicyController

EVENT_TO_STATE = {"authorization": "authorized", "capture": "captured", "settlement": "settled", "void": "voided",
                  "dispute_opened": "disputed"}


def _credential_ref_ok(ref: str) -> bool:
    return isinstance(ref, str) and ref.isupper() and "=" not in ref and " " not in ref and len(ref) <= 64


class RouterBooks:
    """Ledger entries for the router. Amounts are integer KRW; nothing is posted twice for one event key."""

    def __init__(self, ledger: Ledger, mandate: Mandate):
        self.ledger = ledger
        self.mandate = mandate

    def _post(self, tx: Tx, event: str, description: str, lines, key: str, mode: str, ref_type=None, ref_id=None,
              provisional=False, metadata=None) -> str:
        return self.ledger.post(tx, Entry(event, description, tuple(lines), key, mode, ref_type, ref_id, provisional, metadata or {}))

    # -- provider side ---------------------------------------------------------------------------------------

    def prepay_provider(self, tx: Tx, mode: str, action_id: str, provider: str, amount_krw: int, fx_cost_krw: int, event_key: str) -> str:
        lines = [dr(L.PROVIDER_PREPAID, amount_krw, f"credits at {provider}"), cr(L.CASH, amount_krw)]
        if fx_cost_krw:
            lines += [dr(L.FX_COST, fx_cost_krw, "conversion cost"), cr(L.CASH, fx_cost_krw)]
        return self._post(tx, "provider_prepayment", f"prepaid {provider} ({action_id})", lines, event_key, mode, "provider", provider,
                          metadata={"action_id": action_id})

    def provider_prepaid_balance(self, tx: Tx, mode: str, provider: str) -> int:
        """Prepayments booked to the provider minus what executions funded from prepaid credits consumed."""
        paid = self.ledger.reference_balance(tx, L.PROVIDER_PREPAID, "provider", provider, mode)
        used = int(tx.scalar(
            "SELECT COALESCE(SUM(x.cost_krw), 0) FROM route_executions x JOIN model_catalog m ON m.id = x.catalog_id "
            "WHERE x.mode = ? AND m.provider = ? AND x.funding = 'prepaid'", (mode, provider)))
        return paid - used

    def consume_provider(self, tx: Tx, mode: str, request_id: str, execution_id: str, provider: str, cost_krw: int, prepaid: bool,
                         event_key: str) -> str | None:
        """The platform paid the provider for one call: inference cost, from prepaid credits or as a payable."""
        if cost_krw <= 0:
            return None
        lines = [dr(L.INFERENCE_COST, cost_krw, f"{provider} call"), cr(L.PROVIDER_PREPAID if prepaid else L.PAYABLE, cost_krw)]
        return self._post(tx, "inference_cost", f"provider cost for {request_id}", lines, event_key, mode, "routed_request", request_id,
                          metadata={"provider": provider, "execution_id": execution_id, "funding": "prepaid" if prepaid else "payable"})

    # -- customer side ---------------------------------------------------------------------------------------

    def settle_topup(self, tx: Tx, mode: str, customer_id: str, action_id: str, amount: int, processor_fee: int, event_key: str) -> str:
        """The processor paid a top-up out: it becomes a spendable balance the platform owes the customer."""
        if processor_fee < 0 or processor_fee >= amount:
            raise OpsError(f"top-up {action_id}: processor fee {processor_fee} outside 0..{amount}")
        lines = [dr(L.CASH, amount - processor_fee, "payout"), cr(L.CUSTOMER_BALANCES, amount, "prepaid balance")]
        if processor_fee:
            lines.append(dr(L.PAYMENT_FEES, processor_fee))
        return self._post(tx, "customer_topup", f"top-up settled for {customer_id}", lines, event_key, mode, "customer", customer_id,
                          metadata={"action_id": action_id})

    def refund_topup(self, tx: Tx, mode: str, customer_id: str, amount: int, event_key: str) -> str:
        return self._post(tx, "topup_refund", f"top-up refunded to {customer_id}", [dr(L.CUSTOMER_BALANCES, amount), cr(L.CASH, amount)],
                          event_key, mode, "customer", customer_id)

    def customer_balance(self, tx: Tx, mode: str, customer_id: str) -> int:
        """Settled top-ups minus what the customer's requests consumed, plus what was credited back."""
        row = tx.fetchone(
            "SELECT COALESCE(SUM(l.credit), 0) AS c, COALESCE(SUM(l.debit), 0) AS d FROM journal_lines l "
            "JOIN journal_entries e ON e.id = l.entry_id LEFT JOIN routed_requests r ON r.id = e.reference_id AND e.reference_type = 'routed_request' "
            "WHERE e.mode = ? AND l.account_code = ? AND ((e.reference_type = 'customer' AND e.reference_id = ?) OR r.customer_id = ?)",
            (mode, L.CUSTOMER_BALANCES, customer_id, customer_id))
        return int(row["c"]) - int(row["d"])

    def _revenue_lines(self, charge: int, tax: int, request_id: str) -> tuple[list, int]:
        net = charge - tax
        if charge <= 0 or tax < 0 or net < 0:
            raise OpsError(f"request {request_id}: charge {charge} and tax {tax} do not make sense")
        lines = [cr(L.GROSS_SALES, net, "routed request")]
        if tax:
            lines.append(cr(L.TAX_PAYABLE, tax))
        provision = round(net * self.mandate.rate("reserves.dispute_reserve_rate"))
        if provision:
            lines += [dr(L.DISPUTE_PROVISION_EXPENSE, provision), cr(L.DISPUTE_PROVISION, provision)]
        return lines, provision

    def charge_balance(self, tx: Tx, mode: str, request_id: str, charge: int, tax: int) -> str:
        """platform_credits: the request consumes the customer's settled balance; revenue is recognized now."""
        lines, provision = self._revenue_lines(charge, tax, request_id)
        lines.insert(0, dr(L.CUSTOMER_BALANCES, charge, "consumed"))
        return self._post(tx, "request_charged", f"charged request {request_id} from balance", lines, f"request:{request_id}:charge", mode,
                          "routed_request", request_id, provisional=True, metadata={"dispute_provision": provision})

    def invoice(self, tx: Tx, mode: str, request_id: str, charge: int, tax: int, event_key: str) -> str:
        """own_keys: the fee is captured by the processor; receivable until it settles."""
        lines, provision = self._revenue_lines(charge, tax, request_id)
        lines.insert(0, dr(L.RECEIVABLE, charge))
        return self._post(tx, "request_invoiced", f"invoiced request {request_id}", lines, event_key, mode, "routed_request", request_id,
                          provisional=True, metadata={"dispute_provision": provision})

    def settle_invoice(self, tx: Tx, mode: str, request_id: str, charge: int, payout: int, processor_fee: int, event_key: str) -> str:
        if payout + processor_fee != charge:
            raise OpsError(f"request {request_id}: payout {payout} + fee {processor_fee} != charge {charge}")
        lines = [dr(L.CASH, payout, "payout"), cr(L.RECEIVABLE, charge)]
        if processor_fee:
            lines.append(dr(L.PAYMENT_FEES, processor_fee))
        return self._post(tx, "request_settled", f"settled request {request_id}", lines, event_key, mode, "routed_request", request_id)

    def refund(self, tx: Tx, mode: str, request_id: str, charge: int, tax: int, amount: int, to: str, event_key: str) -> str:
        """Refund part or all of a charge: `to` is balance (credited back), cash (settled invoice) or receivable."""
        if amount <= 0 or amount > charge:
            raise OpsError(f"request {request_id}: refund {amount} outside 0..{charge}")
        tax_share = round(amount * tax / charge) if charge else 0
        account = {"balance": L.CUSTOMER_BALANCES, "cash": L.CASH, "receivable": L.RECEIVABLE}[to]
        lines = [dr(L.REFUNDS, amount - tax_share), cr(account, amount)]
        if tax_share:
            lines.append(dr(L.TAX_PAYABLE, tax_share))
        return self._post(tx, "request_refund", f"refund {amount} on request {request_id}", lines, event_key, mode, "routed_request", request_id)

    def release_dispute_provision(self, tx: Tx, mode: str, request_id: str) -> str | None:
        left = self.ledger.reference_balance(tx, L.DISPUTE_PROVISION, "routed_request", request_id, mode)
        key = f"request:{request_id}:dispute_provision_release"
        if left <= 0 or self.ledger.posted(tx, key):
            return None
        return self._post(tx, "dispute_provision_release", f"released dispute provision on request {request_id}",
                          [dr(L.DISPUTE_PROVISION, left), cr(L.DISPUTE_PROVISION_EXPENSE, left)], key, mode, "routed_request", request_id)

    def open_dispute(self, tx: Tx, mode: str, request_id: str, amount: int, event_key: str) -> str | None:
        held = self.ledger.reference_balance(tx, L.DISPUTE_PROVISION, "routed_request", request_id, mode)
        top_up = max(0, amount - held)
        if not top_up:
            return None
        return self._post(tx, "dispute_opened", f"dispute on request {request_id}",
                          [dr(L.DISPUTE_PROVISION_EXPENSE, top_up), cr(L.DISPUTE_PROVISION, top_up)], event_key, mode, "routed_request",
                          request_id, provisional=True)

    def lose_dispute(self, tx: Tx, mode: str, request_id: str, amount: int, fee_krw: int, event_key: str) -> str:
        held = self.ledger.reference_balance(tx, L.DISPUTE_PROVISION, "routed_request", request_id, mode)
        use = min(held, amount)
        lines = [cr(L.CASH, amount + fee_krw)]
        if use:
            lines.append(dr(L.DISPUTE_PROVISION, use))
        if amount - use:
            lines.append(dr(L.CHARGEBACKS, amount - use))
        if fee_krw:
            lines.append(dr(L.PAYMENT_FEES, fee_krw, "dispute fee"))
        return self._post(tx, "dispute_lost", f"chargeback on request {request_id}", lines, event_key, mode, "routed_request", request_id)


class Billing:
    """Customer accounts and the processor-facing side: top-ups, invoices, processor events, refunds."""

    def __init__(self, db: Database, gateway: ActionGateway, books: RouterBooks, mandate: Mandate, policy: PolicyController,
                 audit: AuditTrail):
        self.db = db
        self.gateway = gateway
        self.books = books
        self.mandate = mandate
        self.policy = policy
        self.audit = audit

    # -- customers --------------------------------------------------------------------------------------------

    def register_customer(self, mode: str, customer_id: str, name: str, billing_mode: str, processor: str | None, vat_rate: float,
                          region: str, provider_credentials: list[dict] | None = None, cache_scope: str = "customer",
                          vat_basis: str | None = None, actor: str = "owner", *, terms_accepted_at: str | None = None,
                          ai_disclosure_confirmed: bool = False, prc_opt_in: bool = False) -> dict:
        """Register a tenant. `region` is the customer's country (end users are screened against each provider's supported
        list); `terms_accepted_at` records acceptance of the platform terms that pass down every provider's usage policy;
        `ai_disclosure_confirmed` is the customer's confirmation that their product discloses AI at session start and labels
        outputs (AI Basic Act Art. 31); `prc_opt_in` allows PRC-hosted endpoints for non-personal data."""
        if billing_mode not in BILLING_MODES:
            raise OpsError(f"billing_mode must be one of {BILLING_MODES}")
        if not terms_accepted_at:
            raise OpsError("a customer accepts the platform terms (which pass down each provider's usage policy and supported-regions "
                           "rules) before registration: terms_accepted_at is required")
        if not ai_disclosure_confirmed:
            raise OpsError("the customer must confirm AI disclosure at session start and output labelling (AI Basic Act Art. 31) "
                           "before any request is routed")
        if not region or not str(region).strip():
            raise OpsError("region is the customer's country; end users are screened by country against each provider's supported list")
        if not self.mandate.permits_billing_mode(billing_mode) and mode == LIVE:
            raise OpsError(f"the mandate does not permit billing mode {billing_mode}")
        if not 0 <= vat_rate <= 1:
            raise OpsError("vat_rate must be between 0 and 1")
        if vat_rate == 0 and not vat_basis:
            raise OpsError("a zero VAT rate needs its basis (e.g. the export rule relied on)")
        if cache_scope != "customer":
            raise OpsError("cache_scope is always customer: the semantic cache is per tenant, never shared across customers")
        creds = provider_credentials or []
        for c in creds:
            if not isinstance(c, dict) or not c.get("provider") or not _credential_ref_ok(c.get("credential_ref", "")):
                raise OpsError("provider_credentials are [{provider, credential_ref}] where credential_ref is an environment-variable "
                               "name (UPPER_CASE); a key value is never stored")
        if billing_mode == "own_keys" and not creds:
            raise OpsError("an own_keys customer needs at least one provider credential reference")
        if mode == "simulated" and processor and not processor.startswith("simulated:"):
            raise OpsError("a simulated customer uses a simulated: processor")
        from ..common import canonical_json
        with self.db.transaction() as tx:
            existing = tx.fetchone("SELECT * FROM customers WHERE id = ?", (customer_id,))
            if existing:
                return self._customer(existing)
            row = {"id": customer_id, "name": name, "billing_mode": billing_mode, "processor": processor, "vat_rate_bp": round(vat_rate * 10_000),
                   "vat_basis": vat_basis, "region": str(region).strip().lower(), "provider_credentials": canonical_json(creds),
                   "cache_scope": cache_scope, "terms_accepted_at": terms_accepted_at, "ai_disclosure_confirmed": 1,
                   "prc_opt_in": int(bool(prc_opt_in)), "created_at": now_iso(), "mode": mode}
            tx.insert("customers", row)
            self.audit.record(tx, actor, "customer_registered", "customers", customer_id, after=row)
            return self._customer(row)

    @staticmethod
    def _customer(row: dict) -> dict:
        out = dict(row)
        out["provider_credentials"] = loads(row["provider_credentials"], [])
        out["vat_rate"] = int(row["vat_rate_bp"]) / 10_000
        out["ai_disclosure_confirmed"] = bool(row["ai_disclosure_confirmed"])
        out["prc_opt_in"] = bool(row["prc_opt_in"])
        return out

    def customer(self, tx: Tx, customer_id: str) -> dict:
        row = tx.fetchone("SELECT * FROM customers WHERE id = ?", (customer_id,))
        if not row:
            raise OpsError(f"unknown customer {customer_id}")
        return self._customer(row)

    def balance(self, tx: Tx, mode: str, customer_id: str) -> int:
        return self.books.customer_balance(tx, mode, customer_id)

    # -- collecting money ------------------------------------------------------------------------------------

    def topup(self, mode: str, customer_id: str, amount_krw: int, idempotency_key: str, actor: str = "customer") -> Action:
        """A prepaid top-up: a customer_payment action the processor's events will advance and settle."""
        with self.db.transaction() as tx:
            c = self.customer(tx, customer_id)
            if c["billing_mode"] != "platform_credits":
                raise OpsError(f"customer {customer_id} is billed on own keys; no prepaid balance")
            if amount_krw <= 0:
                raise OpsError("top-up amount must be positive")
            request = ActionRequest("customer_payment", idempotency_key, mode, amount_krw, amount_krw, "KRW", c["processor"], None, None,
                                    "customer", customer_id, {"purpose": "topup", "customer_id": customer_id})
            return self.gateway.submit(request, actor, tx)

    def invoice(self, tx: Tx, mode: str, request_row: dict, actor: str = "system") -> Action:
        """own_keys: bill the platform fee for one delivered request through the processor."""
        c = self.customer(tx, request_row["customer_id"])
        charge = int(request_row["charge_krw"])
        if charge <= 0:
            raise OpsError(f"request {request_row['id']}: nothing to invoice")
        request = ActionRequest("customer_payment", f"invoice:{mode}:{request_row['id']}", mode, charge, charge, "KRW", c["processor"], None, None,
                                "routed_request", request_row["id"], {"purpose": "invoice", "customer_id": c["id"], "fee_krw": int(request_row["fee_krw"])})
        return self.gateway.submit(request, actor, tx)

    # -- processor events ------------------------------------------------------------------------------------

    def apply_event(self, event: dict[str, Any], actor: str = "processor") -> Action:
        """One processor event {source, kind, reference, mode, action_id, amount, payout, processor_fee, outcome, fee}."""
        with self.db.transaction() as tx:
            return self._apply(tx, event, actor)

    def _apply(self, tx: Tx, event: dict[str, Any], actor: str) -> Action:
        action = self.gateway.get(tx, event["action_id"])
        if action.kind != "customer_payment":
            raise OpsError(f"action {action.id} is a {action.kind}, not a customer payment")
        kind = event["kind"]
        amount = int(event.get("amount") or action.amount_krw)
        if kind == "refund":
            refunded = self._refunded_total(tx, action.id) + amount
            to_state = "refunded" if refunded >= action.amount_krw else "partially_refunded"
        elif kind == "dispute_closed":
            to_state = "dispute_won" if event.get("outcome") == "won" else "dispute_lost"
        else:
            try:
                to_state = EVENT_TO_STATE[kind]
            except KeyError:
                raise OpsError(f"unknown payment event kind {kind!r}") from None
        if kind == "authorization" and event.get("status", "confirmed") == "failed":
            return self.gateway.transition(tx, action.id, "failed", reason=event.get("error", "declined"), actor=actor)
        confirmation = {"source": event["source"], "kind": kind, "reference": event["reference"], "mode": event.get("mode", action.mode),
                        "amount": amount, "currency": "KRW", "payload": event.get("payload", {})}
        action = self.gateway.transition(tx, action.id, to_state, confirmation=confirmation, actor=actor)
        key = f"payment:{action.id}:{kind}:{event['reference']}"
        settled = self._has(tx, action.id, "settlement")
        if action.reference_type == "customer":
            customer_id = action.reference_id
            if kind == "settlement":
                self.books.settle_topup(tx, action.mode, customer_id, action.id, amount, int(event.get("processor_fee", 0)), key)
            elif kind == "refund":
                if not settled:
                    raise OpsError("a top-up that has not settled cannot be refunded from the balance; void it at the processor")
                self.books.refund_topup(tx, action.mode, customer_id, amount, key)
            return action
        # an invoice for one routed request
        req = tx.fetchone("SELECT * FROM routed_requests WHERE id = ?", (action.reference_id,))
        if not req:
            raise OpsError(f"payment {action.id} references unknown request {action.reference_id}")
        charge, tax = int(req["charge_krw"]), int(req["tax_krw"])
        if kind == "capture":
            self.books.invoice(tx, action.mode, req["id"], charge, tax, key)
            self._set_status(tx, req, "invoiced")
        elif kind == "settlement":
            fee = int(event.get("processor_fee", 0))
            self.books.settle_invoice(tx, action.mode, req["id"], charge, int(event.get("payout", charge - fee)), fee, key)
            self._set_status(tx, req, "settled", window=True)
        elif kind == "refund":
            self.books.refund(tx, action.mode, req["id"], charge, tax, amount, "cash" if settled else "receivable", key)
            if to_state == "refunded":
                self.books.release_dispute_provision(tx, action.mode, req["id"])
                self._set_status(tx, req, "refunded")
        elif kind == "dispute_opened":
            self.books.open_dispute(tx, action.mode, req["id"], amount, key)
            self._set_status(tx, req, "disputed")
        elif kind == "dispute_closed":
            if to_state == "dispute_won":
                self.books.release_dispute_provision(tx, action.mode, req["id"])
                self._set_status(tx, req, "settled" if settled else "invoiced", window=settled)
            else:
                self.books.lose_dispute(tx, action.mode, req["id"], amount, int(event.get("fee", 0)), key)
                self._set_status(tx, req, "chargeback")
        return action

    def _has(self, tx: Tx, action_id: str, kind: str) -> bool:
        return tx.fetchone("SELECT id FROM external_confirmations WHERE action_id = ? AND kind = ?", (action_id, kind)) is not None

    def _refunded_total(self, tx: Tx, action_id: str) -> int:
        return int(tx.scalar("SELECT COALESCE(SUM(amount), 0) FROM external_confirmations WHERE action_id = ? AND kind = 'refund'", (action_id,)))

    def _set_status(self, tx: Tx, req: dict, status: str, window: bool = False) -> None:
        changes = {"status": status, "updated_at": now_iso()}
        if window and not req.get("dispute_window_ends"):
            changes["dispute_window_ends"] = iso(utcnow() + timedelta(days=self.mandate.days("reserves.refund_reserve_days")))
        tx.update("routed_requests", "id", req["id"], changes)

    # -- refunds we initiate ---------------------------------------------------------------------------------

    def refund_request(self, request_id: str, amount: int, reason: str, actor: str = "support") -> dict:
        """Refund a charged request within policy: back to the balance (platform_credits) or through the processor (own_keys)."""
        with self.db.transaction() as tx:
            req = tx.fetchone("SELECT * FROM routed_requests WHERE id = ?", (request_id,))
            if not req:
                raise OpsError(f"unknown request {request_id}")
            charge = int(req["charge_krw"])
            request = ActionRequest("refund", f"refund:{request_id}:{amount}", req["mode"], amount, amount, "KRW",
                                    self.customer(tx, req["customer_id"])["processor"], None, None, "routed_request", request_id, {"reason": reason})
            self.policy.evaluate(tx, request, actor).raise_if_refused()
            if amount <= 0 or amount > charge:
                raise OpsError(f"refund {amount} exceeds the charge {charge}")
            if req["billing_mode"] == "platform_credits":
                if req["status"] not in ("settled", "closed"):
                    raise InvalidTransition(f"request {request_id} is {req['status']}; nothing was charged")
                self.books.refund(tx, req["mode"], request_id, charge, int(req["tax_krw"]), amount, "balance", f"request:{request_id}:refund:{amount}")
                self.books.release_dispute_provision(tx, req["mode"], request_id)
                tx.update("routed_requests", "id", request_id, {"status": "refunded", "updated_at": now_iso()})
                self.audit.record(tx, actor, "request_refunded", "routed_requests", request_id, after={"amount": amount, "reason": reason})
                return {"request_id": request_id, "refunded_krw": amount, "to": "balance"}
            if not req["payment_id"]:
                raise OpsError(f"request {request_id} has no invoice to refund")
            action = self.gateway.get(tx, req["payment_id"])
            capture = tx.fetchone("SELECT external_reference FROM external_confirmations WHERE action_id = ? AND kind = 'capture'", (action.id,))
            if not capture:
                raise OpsError(f"request {request_id}: the invoice was never captured")
            adapter = self.gateway.adapter(tx, action)
            result = adapter.refund(action.id, capture["external_reference"], amount, "KRW")
            if result.status != "confirmed":
                self.gateway.note_error(tx, action.id, result.error or "refund failed")
                raise OpsError(f"processor did not confirm the refund: {result.error}")
            self._apply(tx, {"source": result.source, "kind": "refund", "reference": result.reference, "mode": result.mode,
                             "action_id": action.id, "amount": amount, "payload": {"reason": reason}}, actor)
            return {"request_id": request_id, "refunded_krw": amount, "to": "processor"}
