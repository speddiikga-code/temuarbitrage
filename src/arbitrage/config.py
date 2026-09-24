"""Settings from the bundled default.toml, an optional user TOML file and a .env file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .errors import ConfigError
from .matching import MatchSettings
from .pricing import Policy


@dataclass(frozen=True)
class Settings:
    fx_fallback: dict[str, float]
    policy: Policy
    fee_rates: dict[str, float]
    match: MatchSettings
    aliexpress_shipping_krw: float


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: str | Path | None = None) -> Settings:
    data = tomllib.loads(resources.files("arbitrage").joinpath("default.toml").read_text("utf-8"))
    if path:
        try:
            with open(path, "rb") as f:
                data = _merge(data, tomllib.load(f))
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"can't load config {path}: {e}") from e
    try:
        return Settings(
            fx_fallback={code: float(rate) for code, rate in data["fx"].items()},
            policy=Policy(**data["policy"]),
            fee_rates={name: float(m["fee_rate"]) for name, m in data["marketplaces"].items()},
            match=MatchSettings(**data["matching"]),
            aliexpress_shipping_krw=float(data["sources"]["aliexpress"]["default_shipping_krw"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise ConfigError(f"bad config value: {e}") from e


def load_dotenv(path: str | Path = ".env", environ=os.environ) -> None:
    """Minimal .env reader: KEY=value lines; real environment variables win."""
    try:
        lines = Path(path).read_text("utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if value:
            environ.setdefault(key.strip(), value)
