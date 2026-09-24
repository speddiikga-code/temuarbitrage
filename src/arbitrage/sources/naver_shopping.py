"""Naver Shopping Search API: what the same product sells for across Korean malls.

Docs: https://developers.naver.com/docs/serviceapi/search/shopping/shopping.md
Free tier: 25,000 calls/day. Unlike the Commerce API, it needs no whitelisted IP.
"""

from __future__ import annotations

import os

import requests

from ..errors import ConfigError, SourceError
from ..matching import clean_html
from ..models import Offer

API_URL = "https://openapi.naver.com/v1/search/shop.json"
PAGE_SIZE = 100
MAX_START = 1000
# productType 1-3: new items on sale (4-6 used, 7-9 discontinued, 10-12 pre-order).
ON_SALE_TYPES = {1, 2, 3}


def parse_items(items: list[dict]) -> list[Offer]:
    offers = []
    for item in items:
        try:
            product_type = int(item.get("productType") or 1)
            price = float(item["lprice"])
        except (KeyError, TypeError, ValueError):
            continue
        if product_type not in ON_SALE_TYPES or price <= 0:
            continue
        offers.append(
            Offer(
                platform="naver",
                title=clean_html(item.get("title", "")),
                price=price,
                currency="KRW",
                url=item.get("link", ""),
                image_url=item.get("image") or None,
                seller=item.get("mallName") or None,
                brand=item.get("brand") or None,
                product_id=str(item.get("productId") or "") or None,
                cross_border=False,
            )
        )
    return offers


class NaverShopping:
    name = "naver"

    def __init__(self, client_id: str, client_secret: str, session=None, exclude: str = "used:rental", timeout: float = 10):
        self.headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
        self.session = session or requests.Session()
        self.exclude = exclude
        self.timeout = timeout

    @classmethod
    def from_env(cls, env=os.environ, **kwargs) -> NaverShopping:
        client_id, secret = env.get("NAVER_CLIENT_ID"), env.get("NAVER_CLIENT_SECRET")
        if not client_id or not secret:
            raise ConfigError("set NAVER_CLIENT_ID and NAVER_CLIENT_SECRET (see .env.example)")
        return cls(client_id, secret, **kwargs)

    def search(self, query: str, limit: int = PAGE_SIZE) -> list[Offer]:
        offers: list[Offer] = []
        start = 1
        while len(offers) < limit and start <= MAX_START:
            display = min(PAGE_SIZE, limit - len(offers))
            params = {"query": query, "display": display, "start": start, "sort": "sim"}
            if self.exclude:
                params["exclude"] = self.exclude
            try:
                resp = self.session.get(API_URL, params=params, headers=self.headers, timeout=self.timeout)
            except requests.RequestException as e:
                raise SourceError(f"Naver Shopping unreachable: {e}") from e
            if resp.status_code != 200:
                raise SourceError(f"Naver Shopping API {resp.status_code}: {resp.text[:200]}")
            items = resp.json().get("items", [])
            offers.extend(parse_items(items))
            if len(items) < display:
                break
            start += display
        return offers[:limit]
