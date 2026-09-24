"""AliExpress Affiliate API (official): supplier-side prices, shipped to Korea, in KRW.

Uses `aliexpress.affiliate.product.query` on the api-sg gateway, signed like the
official SDK: MD5(secret + sorted key/value pairs + secret), uppercase hex.
"""

from __future__ import annotations

import hashlib
import os
import time

import requests

from ..errors import ConfigError, SourceError
from ..models import Offer

API_URL = "https://api-sg.aliexpress.com/sync"
METHOD = "aliexpress.affiliate.product.query"
PAGE_SIZE = 50


def sign(secret: str, params: dict[str, str]) -> str:
    payload = secret + "".join(f"{key}{params[key]}" for key in sorted(params)) + secret
    return hashlib.md5(payload.encode("utf-8")).hexdigest().upper()


def _price(value) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_products(products: list[dict], default_shipping: float = 0.0) -> list[Offer]:
    offers = []
    for p in products:
        price = _price(p.get("target_sale_price")) or _price(p.get("target_app_sale_price"))
        currency = p.get("target_sale_price_currency") or p.get("target_app_sale_price_currency") or "KRW"
        if not price or not p.get("product_title"):
            continue
        offers.append(
            Offer(
                platform="aliexpress",
                title=p["product_title"],
                price=price,
                currency=currency,
                url=p.get("product_detail_url") or p.get("promotion_link") or "",
                shipping=default_shipping,
                image_url=p.get("product_main_image_url") or None,
                seller=str(p["shop_id"]) if p.get("shop_id") else None,
                product_id=str(p["product_id"]) if p.get("product_id") else None,
                cross_border=True,
            )
        )
    return offers


class AliExpress:
    name = "aliexpress"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        tracking_id: str | None = None,
        session=None,
        default_shipping: float = 0.0,
        timeout: float = 15,
        clock=time.time,
    ):
        self.app_key = app_key
        self.app_secret = app_secret
        self.tracking_id = tracking_id
        self.session = session or requests.Session()
        self.default_shipping = default_shipping
        self.timeout = timeout
        self.clock = clock

    @classmethod
    def from_env(cls, env=os.environ, **kwargs) -> AliExpress:
        key, secret = env.get("ALIEXPRESS_APP_KEY"), env.get("ALIEXPRESS_APP_SECRET")
        if not key or not secret:
            raise ConfigError("set ALIEXPRESS_APP_KEY and ALIEXPRESS_APP_SECRET (see .env.example)")
        return cls(key, secret, tracking_id=env.get("ALIEXPRESS_TRACKING_ID") or None, **kwargs)

    def _call(self, app_params: dict[str, str]) -> dict:
        system = {
            "app_key": self.app_key,
            "method": METHOD,
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "timestamp": str(int(self.clock() * 1000)),
        }
        system["sign"] = sign(self.app_secret, {**system, **app_params})
        try:
            resp = self.session.post(API_URL, params=system, data=app_params, timeout=self.timeout)
        except requests.RequestException as e:
            raise SourceError(f"AliExpress unreachable: {e}") from e
        if resp.status_code != 200:
            raise SourceError(f"AliExpress API {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        if "error_response" in body:
            err = body["error_response"]
            raise SourceError(f"AliExpress {err.get('code')}: {err.get('msg')} {err.get('sub_msg') or ''}".strip())
        try:
            result = body[METHOD.replace(".", "_") + "_response"]["resp_result"]
        except KeyError:
            raise SourceError(f"unexpected AliExpress response: {str(body)[:200]}") from None
        if result.get("resp_code") != 200:
            raise SourceError(f"AliExpress {result.get('resp_code')}: {result.get('resp_msg')}")
        return result.get("result") or {}

    def search(self, query: str, limit: int = PAGE_SIZE) -> list[Offer]:
        offers: list[Offer] = []
        page = 1
        while len(offers) < limit:
            page_size = min(PAGE_SIZE, limit - len(offers))
            params = {
                "keywords": query,
                "page_no": str(page),
                "page_size": str(page_size),
                "sort": "LAST_VOLUME_DESC",  # proven sellers first
                "ship_to_country": "KR",
                "target_currency": "KRW",
                "target_language": "KO",
            }
            if self.tracking_id:
                params["tracking_id"] = self.tracking_id
            result = self._call(params)
            products = (result.get("products") or {}).get("product") or []
            offers.extend(parse_products(products, self.default_shipping))
            if len(products) < page_size:
                break
            page += 1
        return offers[:limit]
