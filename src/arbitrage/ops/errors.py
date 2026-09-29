"""Errors raised by the operating core. All derive from ArbitrageError so the CLI prints them plainly."""

from arbitrage.errors import ArbitrageError


class OpsError(ArbitrageError):
    """Base class for operating-core errors."""


class MandateError(OpsError):
    """mandate.toml is malformed or a required value is pending."""


class PolicyRefused(OpsError):
    """The policy controller refused an action (pause, pending mandate, unpermitted kind, limit)."""


class BudgetExceeded(OpsError):
    """A reservation would breach headroom, a limit or an allocation source."""


class InvalidTransition(OpsError):
    """A state machine was asked for a transition it does not allow."""


class ConfirmationRequired(OpsError):
    """A transition that means 'money moved' or 'goods arrived' was attempted without an external record."""


class ReconciliationRequired(OpsError):
    """A payment result is ambiguous; it must be reconciled before any retry."""


class IdempotencyConflict(OpsError):
    """The same idempotency key was reused with a different request."""


class NotConfigured(OpsError):
    """A live adapter or integration that does not exist yet was asked to act."""


class OrchestrationError(OpsError):
    """A task or run violates a charter limit (depth, concurrency, credits, permissions)."""
