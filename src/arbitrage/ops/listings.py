"""Listings: a product goes on sale only with certification evidence for that SKU (eligibility report, item 6).

The keyword compliance filter in the scanner is triage; this is the gate.  A listing is proposed with the SKU's
certification evidence (KC / 전파법 / other, or an explicit "not required" with the rule it relies on), verified,
and only then sent to the channel, whose confirmation makes it `listed`.  Listing is a new commitment, so a
purchasing pause blocks it.
"""

from __future__ import annotations

from typing import Any

from .adapters import CONFIRMED
from .db import Database
from .errors import InvalidTransition, OpsError
from .gateway import Action, ActionGateway
from .mandate import Mandate
from .policy import ActionRequest, PolicyController

CERT_KINDS = ("kc_safety_certification", "kc_safety_confirmation", "supplier_conformity", "radio_wave", "other")


class Listings:
    def __init__(self, db: Database, gateway: ActionGateway, mandate: Mandate, policy: PolicyController):
        self.db = db
        self.gateway = gateway
        self.mandate = mandate
        self.policy = policy

    def propose(self, mode: str, channel: str, sku: str, title: str, list_price_krw: int, category: str,
                certification: dict[str, Any], import_mode: str, actor: str = "agent") -> Action:
        """`certification` is {"required": bool, "kind", "number", "evidence" (URL or document ref), "basis"}."""
        request = ActionRequest("listing", f"listing:{mode}:{channel}:{sku}", mode, 0, 0, "KRW", channel, category, sku, "sku", sku,
                                {"title": title, "list_price_krw": list_price_krw, "category": category,
                                 "certification": certification, "import_mode": import_mode})
        return self.gateway.submit(request, actor)

    def verify(self, action_id: str, actor: str = "compliance") -> Action:
        problems: list[str] = []
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state == "verified":
                return action
            if action.state != "proposed":
                raise InvalidTransition(f"listing {action_id} is {action.state}, not proposed")
            cert = action.payload.get("certification") or {}
            if "required" not in cert:
                problems.append("certification.required must be stated per SKU")
            elif cert["required"]:
                if cert.get("kind") not in CERT_KINDS:
                    problems.append(f"certification.kind must be one of {CERT_KINDS}")
                if not cert.get("number") or not cert.get("evidence"):
                    problems.append("a required certification needs its number and an evidence reference")
            else:
                if not cert.get("basis") or not cert.get("evidence"):
                    problems.append("'not required' needs the rule it relies on and an evidence reference")
            if action.payload.get("import_mode") not in ("commercial_resale", "personal_use", "genuine_sample"):
                problems.append("listing needs an import_mode")
            if int(action.payload.get("list_price_krw", 0)) <= 0:
                problems.append("list price must be positive")
            if problems:
                self.gateway.transition(tx, action.id, "rejected", reason="; ".join(problems), actor=actor)
            else:
                action = self.gateway.transition(tx, action.id, "verified", actor=actor)
        if problems:
            raise OpsError("listing rejected: " + "; ".join(problems))
        return action

    def publish(self, action_id: str, actor: str = "system") -> Action:
        with self.db.transaction() as tx:
            action = self.gateway.get(tx, action_id)
            if action.state == "listed":
                return action
            if action.state not in ("verified", "delisted"):
                raise InvalidTransition(f"listing {action_id} is {action.state}; verify certification first")
            self.policy.evaluate(tx, action.request(), actor).raise_if_refused()
            adapter = self.gateway.adapter(tx, action)
            result = adapter.create_listing(action.id, action.sku, action.payload["title"], int(action.payload["list_price_krw"]))
            if result.status == CONFIRMED:
                return self.gateway.transition(tx, action.id, "listed", confirmation=result, actor=actor)
            self.gateway.note_error(tx, action.id, result.error or "channel refused")
        raise OpsError(f"channel did not confirm the listing: {result.error}")
