from __future__ import annotations

import shutil
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.chains.base import FetchResult, TokenNetwork
from app.config import Settings
from app.main import create_app
from app.services.prices import ContractPriceResult, PriceFetchResult
from app.utils.time import utcnow_iso

# Deterministic contract prices for LP-position tests.
FAKE_CONTRACT_PRICES = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": Decimal("2000"),  # WETH
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": Decimal("1"),  # USDC
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": Decimal("60000"),  # WBTC
}


@pytest.fixture
def work_dir():
    """A workspace-local temp directory.

    The DSH Windows sandbox denies access to directories created under the OS
    temp folder with mode 0700, which is what pytest's tmp_path uses.
    """
    path = Path(__file__).resolve().parent / ".test-data" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class FakeAdapter:
    chain = "ethereum"
    providers = ["https://fake-rpc.invalid"]

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        balances: dict[int, str] = {}
        for network in networks:
            if network.is_native:
                balances[network.id] = str(2 * 10**network.decimals)
            elif network.symbol == "USDT":
                balances[network.id] = str(150 * 10**network.decimals)
            else:
                balances[network.id] = "0"
        return FetchResult(balances=balances, provider="fake-rpc", warnings=[])


class FakePriceService:
    def __init__(self, db):
        self.db = db

    async def get_prices(self, token_ids: list[int], force: bool = False) -> PriceFetchResult:
        rows = self.db.fetchall(
            f"SELECT id, symbol FROM tokens WHERE id IN ({','.join('?' for _ in token_ids)})",
            tuple(token_ids),
        ) if token_ids else []
        prices = {}
        for row in rows:
            prices[row["id"]] = Decimal("1") if row["symbol"] in {"USDT", "USDC"} else Decimal("2000")
        return PriceFetchResult(prices=prices, source="test", fetched_at=utcnow_iso())

    async def get_contract_prices(self, chain: str, contracts: list[str]) -> ContractPriceResult:
        prices = {
            contract.lower(): FAKE_CONTRACT_PRICES[contract.lower()]
            for contract in contracts
            if contract.lower() in FAKE_CONTRACT_PRICES
        }
        return ContractPriceResult(
            prices=prices,
            source="test",
            fetched_at=utcnow_iso(),
        )


@pytest.fixture
def app(work_dir):
    settings = Settings(
        database_path=work_dir / "assetx-test.db",
        frontend_dist=work_dir / "missing-dist",
        start_worker=False,
        refresh_interval_seconds=0.01,
        price_cache_seconds=0,
        cors_origins="*",
    )
    application = create_app(settings)
    with TestClient(application) as client:
        # Replace the network adapters and price provider after lifespan setup.
        application.state.adapters["ethereum"] = FakeAdapter()
        application.state.refresh_service.adapters["ethereum"] = FakeAdapter()
        application.state.price_service = FakePriceService(application.state.db)
        application.state.refresh_service.prices = application.state.price_service
        yield application, client


@pytest.fixture
def client(app):
    return app[1]


@pytest.fixture
def live_app(work_dir):
    settings = Settings(
        database_path=work_dir / "assetx-live-test.db",
        frontend_dist=work_dir / "missing-dist",
        start_worker=True,
        refresh_interval_seconds=0.01,
        price_cache_seconds=0,
        cors_origins="*",
    )
    application = create_app(settings)
    with TestClient(application) as client:
        application.state.adapters["ethereum"] = FakeAdapter()
        application.state.refresh_service.adapters["ethereum"] = FakeAdapter()
        application.state.price_service = FakePriceService(application.state.db)
        application.state.refresh_service.prices = application.state.price_service
        yield application, client
