"""Where offers come from. Every source exposes `name` and `search(query, limit) -> list[Offer]`."""

from .aliexpress import AliExpress
from .csv_source import CsvSource
from .naver_shopping import NaverShopping

__all__ = ["AliExpress", "CsvSource", "NaverShopping"]
