"""Offers from a CSV file, for sites without an API you may automate (Temu, 1688, Taobao, wholesale sites).

Required columns: title, price, url
Optional: platform, currency (KRW), shipping (0), image_url, brand, model,
          cross_border (default: true unless currency is KRW)
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..errors import ConfigError
from ..models import Offer

REQUIRED = {"title", "price", "url"}
_TRUE = {"1", "true", "yes", "y"}


class CsvSource:
    def __init__(self, path: str | Path, platform: str | None = None):
        self.path = Path(path)
        self.name = platform or self.path.stem

    def search(self, query: str, limit: int) -> list[Offer]:
        """Returns the file's rows; the file itself is the curated list, so `query` is ignored."""
        try:
            with self.path.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                missing = REQUIRED - set(reader.fieldnames or [])
                if missing:
                    raise ConfigError(f"{self.path}: missing column(s) {', '.join(sorted(missing))}")
                rows = list(reader)
        except OSError as e:
            raise ConfigError(f"can't read {self.path}: {e}") from e

        offers = []
        for line, row in enumerate(rows, start=2):
            try:
                price = float(row["price"].replace(",", ""))
                shipping = float((row.get("shipping") or "0").replace(",", ""))
            except ValueError:
                raise ConfigError(f"{self.path}:{line}: price/shipping must be numbers") from None
            currency = (row.get("currency") or "KRW").strip().upper()
            flag = (row.get("cross_border") or "").strip().lower()
            offers.append(
                Offer(
                    platform=(row.get("platform") or self.name).strip(),
                    title=row["title"].strip(),
                    price=price,
                    currency=currency,
                    url=row["url"].strip(),
                    shipping=shipping,
                    image_url=(row.get("image_url") or "").strip() or None,
                    brand=(row.get("brand") or "").strip() or None,
                    model=(row.get("model") or "").strip() or None,
                    cross_border=flag in _TRUE if flag else currency != "KRW",
                )
            )
        return offers[:limit]
