"""Currency conversion to KRW."""

from __future__ import annotations

import requests

from .errors import ConfigError

LIVE_URL = "https://open.er-api.com/v6/latest/KRW"


class FxRates:
    def __init__(self, krw_per_unit: dict[str, float], origin: str = "config"):
        self._rates = {code.upper(): float(rate) for code, rate in krw_per_unit.items()}
        self._rates["KRW"] = 1.0
        self.origin = origin

    def to_krw(self, amount: float, currency: str) -> float:
        try:
            return amount * self._rates[currency.upper()]
        except KeyError:
            raise ConfigError(f"no exchange rate for {currency}; add it under [fx] in your config") from None

    def rate(self, currency: str) -> float:
        return self.to_krw(1.0, currency)

    @classmethod
    def live(cls, fallback: dict[str, float], session=None, timeout: float = 10) -> FxRates:
        """Today's rates, or `fallback` if the rate service can't be reached."""
        session = session or requests.Session()
        try:
            resp = session.get(LIVE_URL, timeout=timeout)
            resp.raise_for_status()
            per_krw = resp.json()["rates"]
            rates = {code: 1 / value for code, value in per_krw.items() if value}
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return cls(fallback, origin="fallback")
        return cls(rates, origin="live")
