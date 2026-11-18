from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class TokenNetwork:
    id: int
    token_id: int
    symbol: str
    name: str
    chain: str
    contract_address: str | None
    decimals: int
    is_native: bool
    coingecko_id: str | None = None


@dataclass(frozen=True)
class LpPosition:
    """A non-fungible liquidity position read from a position-manager contract.

    ``token*_amount_raw`` values are integer base units. A position is not a
    fungible token, so it is stored and valued separately from ``TokenNetwork``
    balances.
    """

    protocol: str
    collection: str
    contract_address: str
    token_id: str
    pool_address: str
    token0_address: str
    token0_symbol: str
    token0_decimals: int
    token0_amount_raw: str
    token1_address: str
    token1_symbol: str
    token1_decimals: int
    token1_amount_raw: str
    fee_tier: int
    tick_lower: int
    tick_upper: int
    liquidity: str
    in_range: bool


@dataclass
class FetchResult:
    balances: dict[int, str]
    provider: str
    warnings: list[str] = field(default_factory=list)
    positions: list[LpPosition] = field(default_factory=list)
    # Protocols whose position scan completed authoritatively ("uniswap-v3",
    # "uniswap-v4"). A refresh replaces only these protocols' saved rows, so a
    # V4 indexer outage never wipes saved V3 positions and vice versa.
    positions_complete: set[str] = field(default_factory=set)


class ProviderError(RuntimeError):
    pass


class AllProvidersFailed(ProviderError):
    def __init__(self, chain: str, errors: list[str]):
        self.chain = chain
        self.errors = errors
        detail = "; ".join(errors[:4]) if errors else "no providers configured"
        super().__init__(f"all {chain} providers failed: {detail}")


def provider_label(url: str) -> str:
    parsed = urlsplit(url)
    return parsed.netloc or url


def short_error(exc: Exception, limit: int = 180) -> str:
    text = str(exc).strip().replace("\n", " ")
    if not text:
        text = exc.__class__.__name__
    return text[:limit]


class ChainAdapter(ABC):
    chain: str
    providers: list[str]

    def __init__(self, providers: list[str], client: httpx.AsyncClient):
        if not providers:
            raise ValueError(f"no providers configured for {self.chain}")
        self.providers = providers
        self.client = client

    @abstractmethod
    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        raise NotImplementedError
