from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx

from app.chains.base import FetchResult, TokenNetwork
from app.chains.ethereum import ERC20_BALANCE_OF, EthereumAdapter
from app.db import Database
from app.seed import seed_database
from app.services.prices import PriceFetchResult, PriceService
from app.services.refresh import RefreshService
from app.services.repository import get_address, serialize_address
from app.utils.time import utcnow_iso

STETH_CONTRACT = "0xae7ab96520de3a18e5e111b5eaab095312d7fe84"
EARNETH_CONTRACT = "0xbbfc8683c8fe8cf73777fede7ab9574935fea0a4"
OWNER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"


def _network(
    network_id: int,
    symbol: str,
    contract: str | None,
    *,
    native: bool = False,
) -> TokenNetwork:
    return TokenNetwork(
        id=network_id,
        token_id=network_id,
        symbol=symbol,
        name=symbol,
        chain="ethereum",
        contract_address=contract,
        decimals=18,
        is_native=native,
    )


def test_lido_tokens_are_seeded_with_the_canonical_ethereum_contracts(work_dir):
    db = Database(work_dir / "lido-seed.db")
    db.initialize()
    seed_database(db)

    rows = db.fetchall(
        """
        SELECT t.symbol, t.name, t.coingecko_id, tn.chain, tn.contract_address,
               tn.decimals, tn.is_native, tn.enabled
        FROM tokens t
        JOIN token_networks tn ON tn.token_id = t.id
        WHERE t.symbol IN ('STETH', 'EARNETH')
        ORDER BY t.symbol
        """
    )
    assert [row["symbol"] for row in rows] == ["EARNETH", "STETH"]
    by_symbol = {row["symbol"]: row for row in rows}

    assert by_symbol["STETH"]["name"] == "Lido Staked Ether"
    assert by_symbol["STETH"]["coingecko_id"] == "staked-ether"
    assert by_symbol["STETH"]["chain"] == "ethereum"
    assert by_symbol["STETH"]["contract_address"] == STETH_CONTRACT
    assert by_symbol["STETH"]["decimals"] == 18
    assert by_symbol["STETH"]["is_native"] == 0
    assert by_symbol["STETH"]["enabled"] == 1

    assert by_symbol["EARNETH"]["name"] == "Lido Earn ETH"
    assert by_symbol["EARNETH"]["coingecko_id"] == "lido-earn-eth"
    assert by_symbol["EARNETH"]["chain"] == "ethereum"
    assert by_symbol["EARNETH"]["contract_address"] == EARNETH_CONTRACT
    assert by_symbol["EARNETH"]["decimals"] == 18
    assert by_symbol["EARNETH"]["is_native"] == 0
    assert by_symbol["EARNETH"]["enabled"] == 1

    version = db.fetchone("SELECT value FROM app_meta WHERE key = 'seed_version'")
    assert version["value"] == "4"
    db.close()


def test_lido_seed_step_upgrades_an_existing_database(work_dir):
    db = Database(work_dir / "lido-upgrade.db")
    db.initialize()
    seed_database(db)

    # Simulate a database last opened before the Lido step. A token the user
    # deleted from an older seed step must stay deleted.
    db.execute("DELETE FROM tokens WHERE symbol IN ('STETH', 'EARNETH', 'USDT')")
    db.execute("UPDATE app_meta SET value = '3' WHERE key = 'seed_version'")

    seed_database(db)
    symbols = {
        row["symbol"] for row in db.fetchall("SELECT symbol FROM tokens")
    }
    assert "STETH" in symbols
    assert "EARNETH" in symbols
    assert "USDT" not in symbols

    version = db.fetchone("SELECT value FROM app_meta WHERE key = 'seed_version'")
    assert version["value"] == "4"

    # Re-running the seed is idempotent.
    seed_database(db)
    lido_count = db.fetchone(
        "SELECT COUNT(*) AS total FROM tokens WHERE symbol IN ('STETH', 'EARNETH')"
    )
    assert lido_count["total"] == 2
    db.close()


def test_ethereum_adapter_batches_lido_balance_of_calls():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)
        calls.extend(batch)
        results = []
        for call in batch:
            if call["method"] == "eth_getBalance":
                result = hex(2 * 10**18)
            elif call["id"] == "token:2":
                result = hex(5 * 10**18)
            elif call["id"] == "token:3":
                result = hex(3 * 10**18)
            else:  # pragma: no cover - defensive
                result = hex(0)
            results.append({"jsonrpc": "2.0", "id": call["id"], "result": result})
        return httpx.Response(200, json=results)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = EthereumAdapter(["https://eth.invalid"], client)
            return await adapter.fetch_balances(
                OWNER,
                [
                    _network(1, "ETH", None, native=True),
                    _network(2, "STETH", STETH_CONTRACT),
                    _network(3, "EARNETH", EARNETH_CONTRACT),
                ],
            )

    result = asyncio.run(run())
    assert result.provider == "eth.invalid"
    assert result.balances == {1: str(2 * 10**18), 2: str(5 * 10**18), 3: str(3 * 10**18)}
    assert result.warnings == []

    token_calls = {
        call["params"][0]["to"]: call["params"][0]["data"]
        for call in calls
        if call["method"] == "eth_call"
    }
    assert set(token_calls) == {STETH_CONTRACT, EARNETH_CONTRACT}
    owner_word = f"{int(OWNER, 16):064x}"
    assert token_calls[STETH_CONTRACT] == f"{ERC20_BALANCE_OF}{owner_word}"
    assert token_calls[EARNETH_CONTRACT] == f"{ERC20_BALANCE_OF}{owner_word}"


def test_lido_prices_resolve_through_the_seeded_coingecko_ids(work_dir):
    db = Database(work_dir / "lido-prices.db")
    db.initialize()
    seed_database(db)
    token_rows = db.fetchall(
        "SELECT id, symbol FROM tokens WHERE symbol IN ('STETH', 'EARNETH')"
    )
    ids = {row["symbol"]: row["id"] for row in token_rows}
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "coins": {
                    "coingecko:staked-ether": {"price": 1810.25},
                    "coingecko:lido-earn-eth": {"price": 1849.75},
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PriceService(db, client, cache_seconds=0)
            return await service.get_prices([ids["STETH"], ids["EARNETH"]])

    result = asyncio.run(run())
    assert len(requested_urls) == 1
    assert "coingecko:staked-ether" in requested_urls[0]
    assert "coingecko:lido-earn-eth" in requested_urls[0]
    assert result.source == "defillama"
    assert result.prices == {
        ids["STETH"]: Decimal("1810.25"),
        ids["EARNETH"]: Decimal("1849.75"),
    }
    db.close()


class _LidoAdapter:
    chain = "ethereum"
    providers = ["fake-rpc"]

    async def fetch_balances(
        self, address: str, networks: list[TokenNetwork]
    ) -> FetchResult:
        balances: dict[int, str] = {}
        for network in networks:
            if network.is_native:
                balances[network.id] = str(2 * 10**18)
            elif network.symbol == "STETH":
                balances[network.id] = str(5 * 10**18)
            elif network.symbol == "EARNETH":
                balances[network.id] = str(2 * 10**18)
            else:
                balances[network.id] = "0"
        return FetchResult(balances=balances, provider="fake-rpc", warnings=[])


class _LidoPrices:
    def __init__(self, db: Database):
        self.db = db

    async def get_prices(
        self, token_ids: list[int], force: bool = False
    ) -> PriceFetchResult:
        rows = self.db.fetchall(
            f"SELECT id, symbol FROM tokens WHERE id IN ({','.join('?' for _ in token_ids)})",
            tuple(token_ids),
        ) if token_ids else []
        values = {
            "ETH": Decimal("3000"),
            "STETH": Decimal("2995"),
            "EARNETH": Decimal("3060"),
            "USDC": Decimal("1"),
            "USDT": Decimal("1"),
            "PAXG": Decimal("2000"),
            "XAUT": Decimal("2000"),
        }
        prices = {row["id"]: values[row["symbol"]] for row in rows}
        return PriceFetchResult(
            prices=prices, source="test", fetched_at=utcnow_iso()
        )

    async def get_contract_prices(self, chain: str, contracts: list[str]):
        raise AssertionError("Lido assets are registry tokens, not LP tokens")


def test_refresh_persists_and_values_lido_balances(work_dir):
    db = Database(work_dir / "lido-refresh.db")
    db.initialize()
    seed_database(db)
    timestamp = utcnow_iso()
    with db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO addresses(chain, address, tags, created_at, updated_at)
            VALUES ('ethereum', ?, '[]', ?, ?)
            """,
            (OWNER, timestamp, timestamp),
        )
        address_id = int(cursor.lastrowid)

    service = RefreshService(db, {"ethereum": _LidoAdapter()}, _LidoPrices(db))
    summary = asyncio.run(service.refresh_address(address_id))
    assert summary["warning"] is None

    account = serialize_address(db, get_address(db, address_id), limit=None)
    tokens = {token["symbol"]: token for token in account["tokens"]}
    assert set(tokens) == {"ETH", "STETH", "EARNETH"}
    assert tokens["STETH"]["balance"] == "5"
    assert tokens["STETH"]["price_usd"] == "2995"
    assert tokens["STETH"]["value_usd"] == "14975.00"
    assert tokens["EARNETH"]["balance"] == "2"
    assert tokens["EARNETH"]["price_usd"] == "3060"
    assert tokens["EARNETH"]["value_usd"] == "6120.00"
    assert account["total_usd"] == "27095.00"
    assert account["total_status"] == "complete"
    assert account["tracked_token_count"] == 7
    assert account["unpriced_token_count"] == 0
    db.close()
