"""Wire the services together. `build()` is what the CLI, the workers and the tests call."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import AuditTrail
from .books import Books
from .budget import BudgetGovernor
from .db import Database
from .fulfillment import Fulfillment
from .gateway import ActionGateway
from .ledger import Ledger
from .mandate import Mandate, load_mandate
from .payments import Payments
from .policy import Guardrails, PauseControl, PolicyController
from .purchases import Purchasing
from .registry import IntegrationRegistry


@dataclass
class Core:
    db: Database
    mandate: Mandate
    audit: AuditTrail
    ledger: Ledger
    books: Books
    pauses: PauseControl
    registry: IntegrationRegistry
    policy: PolicyController
    governor: BudgetGovernor
    gateway: ActionGateway
    purchasing: Purchasing
    payments: Payments
    fulfillment: Fulfillment
    guardrails: Guardrails
    adapters: dict[str, Any]

    def pause(self, scope: str, reason: str, by: str) -> str:
        with self.db.transaction() as tx:
            return self.pauses.pause(tx, scope, reason, by)

    def resume(self, pause_id: str, by: str) -> bool:
        with self.db.transaction() as tx:
            return self.pauses.resume(tx, pause_id, by)


def build(db: Database | str, mandate: Mandate | str | Path, adapters: dict[str, Any] | None = None) -> Core:
    if isinstance(db, str):
        db = Database(db)
    if not isinstance(mandate, Mandate):
        mandate = load_mandate(mandate)
    db.migrate()
    audit = AuditTrail(db)
    ledger = Ledger(db)
    with db.transaction() as tx:
        ledger.ensure_chart(tx)
    books = Books(ledger, mandate)
    pauses = PauseControl(db, audit)
    registry = IntegrationRegistry(db, audit)
    policy = PolicyController(db, mandate, pauses, audit, registry)
    governor = BudgetGovernor(db, mandate, ledger, audit)
    gateway = ActionGateway(db, policy, governor, audit, registry, adapters or {})
    purchasing = Purchasing(db, gateway, governor, books, mandate, policy)
    payments = Payments(db, gateway, books, mandate, policy, audit)
    fulfillment = Fulfillment(db, gateway, books, mandate, policy, audit)
    guardrails = Guardrails(db, mandate, ledger, pauses, registry)
    if adapters:
        with db.transaction() as tx:
            registry.register_simulated(tx, [n for n in adapters if n.startswith("simulated:")])
    return Core(db, mandate, audit, ledger, books, pauses, registry, policy, governor, gateway, purchasing, payments,
                fulfillment, guardrails, adapters or {})
