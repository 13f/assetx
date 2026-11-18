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
COINGECKO_TOKEN_PRICE_URL = "https://api.coingecko.com/api/v3/simple/token_price/{platform}"

# DefiLlama and CoinGecko both accept an EVM chain slug when pricing by
# contract address. Only Ethereum is wired today because LP positions are
# Ethereum-only.
CONTRACT_PRICE_CHAINS = {"ethereum": "ethereum"}


@dataclass
class PriceFetchResult:
    prices: dict[int, Decimal] = field(default_factory=dict)
    source: str | None = None
    fetched_at: str | None = None
    warning: str | None = None


@dataclass
class ContractPriceResult:
    """USD prices for token contracts, keyed by lowercase contract address."""

    prices: dict[str, Decimal] = field(default_factory=dict)
    source: str | None = None
    fetched_at: str | None = None
    warning: str | None = None


def short_contract(address: str) -> str:
    return f"{address[:6]}..{address[-4:]}" if len(address) > 12 else address


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

    @staticmethod
    def _price_chain(chain: str) -> str | None:
        return CONTRACT_PRICE_CHAINS.get(chain)

    @classmethod
    def normalize_contracts(cls, chain: str, contracts: list[str]) -> list[str]:
        if cls._price_chain(chain) is None:
            return []
        return sorted({contract.strip().lower() for contract in contracts if contract.strip()})

    def _cached_contracts(
        self, chain: str, contracts: list[str], allow_stale: bool = False
    ) -> ContractPriceResult:
        if not contracts:
            return ContractPriceResult()
        placeholders = ",".join("?" for _ in contracts)
        rows = self.db.fetchall(
            f"""
            SELECT contract_address, price_usd, source, fetched_at
            FROM contract_prices
            WHERE chain = ? AND contract_address IN ({placeholders})
            """,
            (chain, *contracts),
        )
        cutoff = utcnow() - timedelta(seconds=self.cache_seconds)
        prices: dict[str, Decimal] = {}
        oldest: str | None = None
        source: str | None = None
        for row in rows:
            fetched = iso_to_datetime(row["fetched_at"])
            if not allow_stale and (fetched is None or fetched < cutoff):
                continue
            prices[row["contract_address"].lower()] = Decimal(row["price_usd"])
            source = source or row["source"]
            if oldest is None or row["fetched_at"] < oldest:
                oldest = row["fetched_at"]
        return ContractPriceResult(prices=prices, source=source, fetched_at=oldest)

    async def _defillama_contracts(
        self, chain: str, contracts: list[str]
    ) -> ContractPriceResult:
        slug = self._price_chain(chain)
        if slug is None:
            return ContractPriceResult(warning=f"No contract price provider for {chain}")
        ids = [f"{slug}:{contract}" for contract in contracts]
        response = await self.client.get(DEFILLAMA_URL + ",".join(ids))
        response.raise_for_status()
        data = response.json()
        coins = data.get("coins") if isinstance(data, dict) else None
        if not isinstance(coins, dict):
            raise ValueError("price provider returned no coins object")
        lookup = {str(key).lower(): value for key, value in coins.items()}
        prices: dict[str, Decimal] = {}
        for contract in contracts:
            item = lookup.get(f"{slug}:{contract}")
            if isinstance(item, dict) and item.get("price") is not None:
                prices[contract] = Decimal(str(item["price"]))
        if not prices:
            raise ValueError("price provider returned no usable contract prices")
        return ContractPriceResult(
            prices=prices, source="defillama", fetched_at=utcnow_iso()
        )

    async def _coingecko_contracts(
        self, chain: str, contracts: list[str]
    ) -> ContractPriceResult:
        platform = self._price_chain(chain)
        if platform is None:
            return ContractPriceResult(warning=f"No contract price provider for {chain}")
        response = await self.client.get(
            COINGECKO_TOKEN_PRICE_URL.format(platform=platform),
            params={"contract_addresses": ",".join(contracts), "vs_currencies": "usd"},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("CoinGecko returned no contract price object")
        lookup = {str(key).lower(): value for key, value in data.items()}
        prices: dict[str, Decimal] = {}
        for contract in contracts:
            item = lookup.get(contract)
            if isinstance(item, dict) and item.get("usd") is not None:
                prices[contract] = Decimal(str(item["usd"]))
        if not prices:
            raise ValueError("CoinGecko returned no usable contract prices")
        return ContractPriceResult(
            prices=prices, source="coingecko", fetched_at=utcnow_iso()
        )

    async def get_contract_prices(
        self, chain: str, contracts: list[str]
    ) -> ContractPriceResult:
        """Price ERC-20 contracts without registering them in the token registry.

        LP positions hold arbitrary underlying tokens, so pricing by contract
        address keeps the curated registry clean while still valuing the
        position. Cache semantics match :meth:`get_prices`.
        """
        normalized = self.normalize_contracts(chain, contracts)
        if not normalized:
            if self._price_chain(chain) is None:
                return ContractPriceResult(
                    warning=f"LP position pricing is not supported on {chain}"
                )
            return ContractPriceResult()
        cached = self._cached_contracts(chain, normalized)
        if len(cached.prices) == len(normalized):
            return cached

        errors: list[str] = []
        for provider in (self._defillama_contracts, self._coingecko_contracts):
            try:
                result = await provider(chain, normalized)
                missing = [
                    contract for contract in normalized if contract not in result.prices
                ]
                if missing:
                    note = "No price for " + ", ".join(
                        short_contract(contract) for contract in missing[:5]
                    )
                    result.warning = f"{result.warning}; {note}" if result.warning else note
                return result
            except Exception as exc:  # noqa: BLE001 - provider fallback
                errors.append(f"{provider.__name__.lstrip('_')}: {str(exc)[:140]}")

        cached = self._cached_contracts(chain, normalized, allow_stale=True)
        if cached.prices:
            cached.warning = "Contract price refresh failed; using cached prices"
            return cached
        return ContractPriceResult(
            warning="Contract price refresh failed: " + "; ".join(errors[:2])
        )

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
