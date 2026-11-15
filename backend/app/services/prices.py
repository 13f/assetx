from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx

from app.db import Database
from app.utils.time import iso_to_datetime, utcnow, utcnow_iso

DEFILLAMA_URL = "https://coins.llama.fi/prices/current/"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


@dataclass
class PriceFetchResult:
    prices: dict[int, Decimal] = field(default_factory=dict)
    source: str | None = None
    fetched_at: str | None = None
    warning: str | None = None


class PriceService:
    def __init__(self, db: Database, client: httpx.AsyncClient, cache_seconds: int = 15):
        self.db = db
        self.client = client
        self.cache_seconds = cache_seconds

    def _tokens(self, token_ids: list[int]) -> list[Any]:
        if not token_ids:
            return []
        placeholders = ",".join("?" for _ in token_ids)
        return self.db.fetchall(
            f"SELECT id, symbol, coingecko_id FROM tokens WHERE id IN ({placeholders})",
            tuple(token_ids),
        )

    def _cached(self, token_ids: list[int], allow_stale: bool = False) -> PriceFetchResult:
        if not token_ids:
            return PriceFetchResult()
        placeholders = ",".join("?" for _ in token_ids)
        rows = self.db.fetchall(
            f"SELECT token_id, price_usd, source, fetched_at FROM prices WHERE token_id IN ({placeholders})",
            tuple(token_ids),
        )
        cutoff = utcnow() - timedelta(seconds=self.cache_seconds)
        prices: dict[int, Decimal] = {}
        oldest: str | None = None
        source: str | None = None
        for row in rows:
            fetched = iso_to_datetime(row["fetched_at"])
            if not allow_stale and (fetched is None or fetched < cutoff):
                continue
            prices[row["token_id"]] = Decimal(row["price_usd"])
            source = source or row["source"]
            if oldest is None or row["fetched_at"] < oldest:
                oldest = row["fetched_at"]
        return PriceFetchResult(prices=prices, source=source, fetched_at=oldest)

    async def _defillama(self, tokens: list[Any]) -> PriceFetchResult:
        ids = [f"coingecko:{row['coingecko_id']}" for row in tokens if row["coingecko_id"]]
        if not ids:
            return PriceFetchResult(warning="No CoinGecko price ids configured")
        response = await self.client.get(DEFILLAMA_URL + ",".join(ids))
        response.raise_for_status()
        data = response.json()
        coins = data.get("coins") or {}
        prices: dict[int, Decimal] = {}
        for row in tokens:
            coingecko_id = row["coingecko_id"]
            if not coingecko_id:
                continue
            item = coins.get(f"coingecko:{coingecko_id}")
            if item and item.get("price") is not None:
                prices[row["id"]] = Decimal(str(item["price"]))
        if not prices:
            raise ValueError("price provider returned no usable prices")
        return PriceFetchResult(prices=prices, source="defillama", fetched_at=utcnow_iso())

    async def _coingecko(self, tokens: list[Any]) -> PriceFetchResult:
        ids = sorted({row["coingecko_id"] for row in tokens if row["coingecko_id"]})
        if not ids:
            return PriceFetchResult(warning="No CoinGecko price ids configured")
        response = await self.client.get(
            COINGECKO_URL,
            params={"ids": ",".join(ids), "vs_currencies": "usd"},
        )
        response.raise_for_status()
        data = response.json()
        prices: dict[int, Decimal] = {}
        for row in tokens:
            item = data.get(row["coingecko_id"] or "")
            if isinstance(item, dict) and item.get("usd") is not None:
                prices[row["id"]] = Decimal(str(item["usd"]))
        if not prices:
            raise ValueError("CoinGecko returned no usable prices")
        return PriceFetchResult(prices=prices, source="coingecko", fetched_at=utcnow_iso())

    async def get_prices(self, token_ids: list[int], force: bool = False) -> PriceFetchResult:
        token_ids = sorted(set(token_ids))
        if not token_ids:
            return PriceFetchResult()
        if not force:
            cached = self._cached(token_ids)
            # Only use the cache when every requested token has a fresh price.
            # A partial hit must not silently leave assets unpriced.
            if len(cached.prices) == len(token_ids):
                return cached

        tokens = self._tokens(token_ids)
        errors: list[str] = []
        for provider in (self._defillama, self._coingecko):
            try:
                result = await provider(tokens)
                missing = [row["symbol"] for row in tokens if row["id"] not in result.prices]
                if missing:
                    note = f"No price for {', '.join(missing)}"
                    result.warning = f"{result.warning}; {note}" if result.warning else note
                return result
            except Exception as exc:  # noqa: BLE001 - provider fallback
                errors.append(f"{provider.__name__.lstrip('_')}: {str(exc)[:140]}")

        cached = self._cached(token_ids, allow_stale=True)
        if cached.prices:
            cached.warning = "Price refresh failed; using cached prices"
            return cached
        return PriceFetchResult(warning="Price refresh failed: " + "; ".join(errors[:2]))
