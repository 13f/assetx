from __future__ import annotations

import asyncio
import json
from decimal import Decimal, localcontext

import httpx
import pytest
from fastapi.testclient import TestClient

from app.chains.base import FetchResult, LpPosition, TokenNetwork
from app.chains.ethereum import EthereumAdapter
from app.chains.registry import chain_meta, lp_collections_for
from app.chains.uniswap import (
    DEFAULT_NFT_COLLECTIONS,
    Q96,
    RpcTransport,
    SEL_BALANCE_OF,
    SEL_DECIMALS,
    SEL_FACTORY,
    SEL_GET_POOL,
    SEL_POSITIONS,
    SEL_SLOT0,
    SEL_SYMBOL,
    SEL_TOKEN_OF_OWNER_BY_INDEX,
    UNISWAP_V3_POSITION_MANAGER,
    UniswapV3Reader,
    decode_abi_string,
    position_amounts,
    sqrt_ratio_at_tick,
)
from app.config import Settings
from app.db import Database
from app.services.prices import PriceService
from app.utils.amounts import amount_from_raw
from app.utils.time import utcnow_iso

OWNER = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
SPAM = "0x1111111111111111111111111111111111111111"
FACTORY = "0x1f98431c8ad98523631ae4a59f267346ea31f984"
POOL = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"


# ---------------------------------------------------------------------------
# ABI helpers
# ---------------------------------------------------------------------------


def word(value: int) -> str:
    return f"{value & ((1 << 256) - 1):064x}"


def address_word(address: str) -> str:
    return f"{int(address, 16):064x}"


def encode_string(text: str) -> str:
    raw = text.encode()
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return "0x" + word(32) + word(len(raw)) + padded.hex()


def encode_position(
    *,
    token0: str = WETH,
    token1: str = USDC,
    fee: int = 500,
    tick_lower: int = -600,
    tick_upper: int = 600,
    liquidity: int = 10**18,
) -> str:
    words = [
        1,  # nonce
        int(OWNER, 16),  # operator
        int(token0, 16),
        int(token1, 16),
        fee,
        tick_lower,
        tick_upper,
        liquidity,
        0,
        0,
        0,
        0,
    ]
    return "0x" + "".join(word(value) for value in words)


def encode_slot0(sqrt_price: int = Q96, tick: int = 0) -> str:
    return "0x" + word(sqrt_price) + word(tick) + "".join(word(0) for _ in range(5))


# ---------------------------------------------------------------------------
# JSON-RPC fakes
# ---------------------------------------------------------------------------

ERROR = object()


def rpc_handler(
    *,
    balance: int = 1,
    token_ids: tuple[int, ...] = (42,),
    position_data: str | None = None,
    slot0_data: str | None = None,
    fail_positions: bool = False,
    fail_position_ids: set[int] | None = None,
    fail_decimals: bool = False,
    requests_seen: list[dict] | None = None,
):
    position_data = position_data or encode_position()
    slot0_data = slot0_data or encode_slot0()

    def dispatch(to: str, data: str):
        if to == UNISWAP_V3_POSITION_MANAGER:
            if data.startswith(SEL_BALANCE_OF):
                return "0x" + word(balance)
            if data.startswith(SEL_TOKEN_OF_OWNER_BY_INDEX):
                index = int(data[-64:], 16)
                if index >= len(token_ids):
                    return ERROR
                return "0x" + word(token_ids[index])
            if data.startswith(SEL_POSITIONS):
                if fail_positions:
                    return ERROR
                token_id = int(data[-64:], 16)
                if fail_position_ids and token_id in fail_position_ids:
                    return ERROR
                return position_data
            if data.startswith(SEL_FACTORY):
                return "0x" + address_word(FACTORY)
        if to == FACTORY and data.startswith(SEL_GET_POOL):
            return "0x" + address_word(POOL)
        if to == POOL and data.startswith(SEL_SLOT0):
            return slot0_data
        if to == WETH:
            if data.startswith(SEL_SYMBOL):
                return encode_string("WETH")
            if data.startswith(SEL_DECIMALS):
                return ERROR if fail_decimals else "0x" + word(18)
        if to == USDC:
            if data.startswith(SEL_SYMBOL):
                return encode_string("USDC")
            if data.startswith(SEL_DECIMALS):
                return "0x" + word(6)
        return ERROR

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read().decode())
        responses = []
        for item in payload:
            if requests_seen is not None:
                requests_seen.append(item)
            result = None
            if item["method"] == "eth_getBalance":
                result = "0xde0b6b3a7640000"
            elif item["method"] == "eth_call":
                params = item["params"][0]
                result = dispatch(params["to"].lower(), params["data"])
            if result is ERROR:
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": item["id"],
                        "error": {"code": -32000, "message": "execution reverted"},
                    }
                )
            else:
                responses.append({"jsonrpc": "2.0", "id": item["id"], "result": result})
        return httpx.Response(200, json=responses)

    return handler


def run_reader(handler, *, max_positions: int = 30):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            reader = UniswapV3Reader(
                RpcTransport(client, "https://rpc.invalid"),
                max_positions=max_positions,
            )
            return await reader.read(OWNER, DEFAULT_NFT_COLLECTIONS)

    return asyncio.run(run())


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def test_sqrt_ratio_matches_uniswap_tick_math():
    assert sqrt_ratio_at_tick(0) == 1 << 96
    product = sqrt_ratio_at_tick(60) * sqrt_ratio_at_tick(-60)
    assert abs(Decimal(product) - Decimal((1 << 192))) / Decimal((1 << 192)) < Decimal(
        "1e-15"
    )
    assert sqrt_ratio_at_tick(1) > sqrt_ratio_at_tick(0)
    assert sqrt_ratio_at_tick(-1) < sqrt_ratio_at_tick(0)
    with pytest.raises(ValueError):
        sqrt_ratio_at_tick(887273)


def test_position_amounts_in_range_are_symmetric_around_tick_zero():
    liquidity = 10**18
    amount0, amount1 = position_amounts(liquidity, Q96, -600, 600)
    assert amount0 == amount1
    with localcontext() as ctx:
        ctx.prec = 50
        sqrt_price = Decimal(Q96)
        sqrt_lower = Decimal(sqrt_ratio_at_tick(-600))
        sqrt_upper = Decimal(sqrt_ratio_at_tick(600))
        expected0 = (
            Decimal(liquidity)
            * (sqrt_upper - sqrt_price)
            * Decimal(Q96)
            / (sqrt_price * sqrt_upper)
        )
        expected1 = Decimal(liquidity) * (sqrt_price - sqrt_lower) / Decimal(Q96)
    assert abs(Decimal(amount0) - expected0) / expected0 < Decimal("1e-12")
    assert abs(Decimal(amount1) - expected1) / expected1 < Decimal("1e-12")


def test_position_amounts_below_range_hold_only_token0():
    liquidity = 10**18
    amount0, amount1 = position_amounts(liquidity, Q96, 60, 120)
    assert amount0 > 0
    assert amount1 == 0


def test_position_amounts_above_range_hold_only_token1():
    liquidity = 10**18
    amount0, amount1 = position_amounts(liquidity, Q96, -120, -60)
    assert amount0 == 0
    assert amount1 > 0


def test_position_amounts_zero_liquidity_or_invalid_range():
    assert position_amounts(0, Q96, -60, 60) == (0, 0)
    assert position_amounts(10**18, Q96, 60, 60) == (0, 0)


def test_decode_abi_string_handles_string_and_bytes32():
    assert decode_abi_string(encode_string("USDC")) == "USDC"
    bytes32 = "0x" + b"MKR".ljust(32, b"\x00").hex()
    assert decode_abi_string(bytes32) == "MKR"
    assert decode_abi_string("0x") == ""


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def test_reader_decodes_a_uniswap_v3_position():
    positions, warnings, complete = run_reader(rpc_handler(balance=1, token_ids=(42,)))
    assert warnings == []
    assert complete is True
    assert len(positions) == 1
    position = positions[0]
    assert position.token_id == "42"
    assert position.protocol == "uniswap-v3"
    assert position.collection == "Uniswap V3"
    assert position.contract_address == UNISWAP_V3_POSITION_MANAGER
    assert position.pool_address == POOL
    assert position.token0_address == WETH
    assert position.token0_symbol == "WETH"
    assert position.token0_decimals == 18
    assert position.token1_address == USDC
    assert position.token1_symbol == "USDC"
    assert position.token1_decimals == 6
    assert position.fee_tier == 500
    assert (position.tick_lower, position.tick_upper) == (-600, 600)
    assert position.in_range is True
    expected0, expected1 = position_amounts(10**18, Q96, -600, 600)
    assert position.token0_amount_raw == str(expected0)
    assert position.token1_amount_raw == str(expected1)
    assert amount_from_raw(position.token0_amount_raw, 18) > 0
    assert amount_from_raw(position.token1_amount_raw, 6) > 0


def test_reader_returns_nothing_for_wallet_without_positions():
    positions, warnings, complete = run_reader(rpc_handler(balance=0))
    assert positions == []
    assert warnings == []
    assert complete is True


def test_reader_marks_out_of_range_positions():
    handler = rpc_handler(
        balance=1,
        position_data=encode_position(tick_lower=-120, tick_upper=-60),
        slot0_data=encode_slot0(tick=0),
    )
    positions, _warnings, complete = run_reader(handler)
    assert complete is True
    assert positions[0].in_range is False
    assert int(positions[0].token0_amount_raw) == 0
    assert int(positions[0].token1_amount_raw) > 0


def test_reader_caps_position_count_with_a_warning():
    handler = rpc_handler(balance=5, token_ids=(1, 2, 3, 4, 5))
    positions, warnings, complete = run_reader(handler, max_positions=2)
    assert complete is True
    assert len(positions) == 2
    assert any("showing 2 of 5 positions" in warning for warning in warnings)


def test_reader_marks_partial_scan_incomplete_but_keeps_decoded_positions():
    handler = rpc_handler(balance=2, token_ids=(42, 43), fail_position_ids={43})
    positions, warnings, complete = run_reader(handler)
    assert complete is False
    assert [position.token_id for position in positions] == ["42"]
    assert any("#43: positions() failed" in warning for warning in warnings)


def test_reader_raises_when_every_position_call_fails():
    handler = rpc_handler(balance=1, fail_positions=True)
    from app.chains.base import ProviderError

    with pytest.raises(ProviderError):
        run_reader(handler)


def test_reader_requires_token_decimals():
    handler = rpc_handler(balance=1, fail_decimals=True)
    positions, warnings, complete = run_reader(handler)
    assert positions == []
    assert complete is False
    assert any("token metadata unavailable" in warning for warning in warnings)


def test_reader_reuses_immutable_contract_metadata():
    seen: list[dict] = []
    handler = rpc_handler(balance=1, requests_seen=seen)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            reader = UniswapV3Reader(RpcTransport(client, "https://rpc.invalid"))
            first = await reader.read(OWNER, DEFAULT_NFT_COLLECTIONS)
            second = await reader.read(OWNER, DEFAULT_NFT_COLLECTIONS)
            return first, second

    first, second = asyncio.run(run())
    assert first[2] is True and second[2] is True

    def calls_to(address: str, selector: str) -> int:
        return sum(
            1
            for item in seen
            if isinstance(item["params"][0], dict)
            and item["params"][0].get("to", "").lower() == address
            and item["params"][0].get("data", "").startswith(selector)
        )

    assert calls_to(WETH, SEL_SYMBOL) == 1
    assert calls_to(WETH, SEL_DECIMALS) == 1
    assert calls_to(UNISWAP_V3_POSITION_MANAGER, SEL_FACTORY) == 1
    assert calls_to(FACTORY, SEL_GET_POOL) == 1
    # The price is read again on every refresh; only static metadata is cached.
    assert calls_to(POOL, SEL_SLOT0) == 2


# ---------------------------------------------------------------------------
# Ethereum adapter integration
# ---------------------------------------------------------------------------


def _networks() -> list[TokenNetwork]:
    return [
        TokenNetwork(1, 1, "ETH", "Ether", "ethereum", None, 18, True),
        TokenNetwork(
            2,
            6,
            "USDC",
            "USD Coin",
            "ethereum",
            USDC,
            6,
            False,
        ),
    ]


def test_ethereum_adapter_fetches_balances_and_positions():
    handler = rpc_handler(balance=1)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = EthereumAdapter(
                ["https://rpc.invalid"],
                client,
                lp_collections=DEFAULT_NFT_COLLECTIONS,
            )
            return await adapter.fetch_balances(OWNER, _networks())

    result = asyncio.run(run())
    assert result.balances[1] == "1000000000000000000"
    assert result.balances[2] == "0"
    assert "uniswap-v3" in result.positions_complete
    assert len(result.positions) == 1
    assert result.positions[0].token_id == "42"


def test_ethereum_adapter_keeps_balances_when_position_scan_fails():
    handler = rpc_handler(balance=1, fail_positions=True)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = EthereumAdapter(
                ["https://rpc.invalid"],
                client,
                lp_collections=DEFAULT_NFT_COLLECTIONS,
            )
            return await adapter.fetch_balances(OWNER, _networks())

    result = asyncio.run(run())
    assert result.balances[1] == "1000000000000000000"
    assert result.positions == []
    assert result.positions_complete == set()
    assert any("Uniswap V3" in warning for warning in result.warnings)


def test_ethereum_adapter_without_lp_collections_skips_position_rpc():
    seen: list[dict] = []
    handler = rpc_handler(balance=1, requests_seen=seen)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = EthereumAdapter(["https://rpc.invalid"], client)
            return await adapter.fetch_balances(OWNER, _networks())

    result = asyncio.run(run())
    assert result.positions == []
    assert result.positions_complete == set()
    assert all(
        not isinstance(item["params"][0], dict)
        or item["params"][0].get("to", "").lower() != UNISWAP_V3_POSITION_MANAGER
        for item in seen
        if item["method"] == "eth_call"
    )


# ---------------------------------------------------------------------------
# Contract pricing
# ---------------------------------------------------------------------------


def test_contract_prices_are_normalized_and_cached(work_dir):
    db = work_dir / "prices.db"
    database = _database(db)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/prices/current/ethereum:0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        return httpx.Response(
            200,
            json={
                "coins": {
                    f"ethereum:{WETH}": {"price": 1809.5, "decimals": 18},
                }
            },
        )

    async def run_first():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PriceService(database, client, cache_seconds=60)
            return await service.get_contract_prices("ethereum", [WETH.upper()])

    result = asyncio.run(run_first())
    assert result.source == "defillama"
    assert result.prices == {WETH: Decimal("1809.5")}
    # The caller persists the cache; emulate that and prove the cache is used.
    database.execute(
        """
        INSERT INTO contract_prices(chain, contract_address, price_usd, source, fetched_at)
        VALUES ('ethereum', ?, '1809.5', 'defillama', ?)
        """,
        (WETH, utcnow_iso()),
    )

    async def run_second():
        transport = httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("network used"))
        )
        async with httpx.AsyncClient(transport=transport) as client:
            service = PriceService(database, client, cache_seconds=60)
            return await service.get_contract_prices("ethereum", [WETH])

    cached = asyncio.run(run_second())
    assert cached.prices == {WETH: Decimal("1809.5")}
    database.close()


def test_contract_prices_fall_back_to_coingecko(work_dir):
    database = _database(work_dir / "prices-fallback.db")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if "coins.llama.fi" in str(request.url):
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={WETH: {"usd": 1234.5}})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PriceService(database, client, cache_seconds=60)
            return await service.get_contract_prices("ethereum", [WETH])

    result = asyncio.run(run())
    assert calls["count"] == 2
    assert result.source == "coingecko"
    assert result.prices == {WETH: Decimal("1234.5")}
    database.close()


def test_contract_prices_report_unsupported_chain(work_dir):
    database = _database(work_dir / "prices-chain.db")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(rpc_handler())) as client:
            service = PriceService(database, client)
            return await service.get_contract_prices("solana", [WETH])

    result = asyncio.run(run())
    assert result.prices == {}
    assert "not supported" in (result.warning or "")
    database.close()


def _database(path):
    from app.db import Database

    database = Database(path)
    database.initialize()
    return database


# ---------------------------------------------------------------------------
# Refresh + API serialization
# ---------------------------------------------------------------------------


def _sample_position(
    *,
    token1_address: str = USDC,
    token1_symbol: str = "USDC",
    token1_decimals: int = 6,
) -> LpPosition:
    return LpPosition(
        protocol="uniswap-v3",
        collection="Uniswap V3",
        contract_address=UNISWAP_V3_POSITION_MANAGER,
        token_id="112161",
        pool_address=POOL,
        token0_address=WETH,
        token0_symbol="WETH",
        token0_decimals=18,
        token0_amount_raw=str(10**17),
        token1_address=token1_address,
        token1_symbol=token1_symbol,
        token1_decimals=token1_decimals,
        token1_amount_raw=str(200 * 10**token1_decimals),
        fee_tier=500,
        tick_lower=-887220,
        tick_upper=887220,
        liquidity="1",
        in_range=True,
    )


class FakePositionAdapter:
    chain = "ethereum"
    providers = ["https://fake-rpc.invalid"]

    def __init__(
        self,
        positions: list[LpPosition],
        complete_protocols: set[str] | None = None,
    ):
        self.positions = positions
        self.positions_complete = (
            {position.protocol for position in positions}
            if complete_protocols is None
            else set(complete_protocols)
        )

    async def fetch_balances(
        self, address: str, networks: list[TokenNetwork]
    ) -> FetchResult:
        balances = {
            network.id: (str(2 * 10**network.decimals) if network.is_native else "0")
            for network in networks
        }
        return FetchResult(
            balances=balances,
            provider="fake-rpc",
            positions=list(self.positions),
            positions_complete=set(self.positions_complete),
        )


def _install_adapter(application, adapter) -> None:
    application.state.adapters["ethereum"] = adapter
    application.state.refresh_service.adapters["ethereum"] = adapter


def test_refresh_persists_lp_positions_and_includes_them_in_the_total(app):
    application, client = app
    created = client.post(
        "/api/addresses", json={"chain": "ethereum", "address": OWNER, "tags": []}
    ).json()
    _install_adapter(application, FakePositionAdapter([_sample_position()]))

    result = asyncio.run(
        application.state.refresh_service.refresh_address(created["id"])
    )
    assert result["position_count"] == 1

    account = client.get(f"/api/addresses/{created['id']}").json()
    assert account["position_count"] == 1
    assert account["unpriced_position_count"] == 0
    assert account["total_status"] == "complete"
    # 2 ETH at 2000 = 4000, plus 0.1 WETH (200) + 200 USDC (200).
    assert account["total_usd"] == "4400.00"
    position = account["positions"][0]
    assert position["token_id"] == "112161"
    assert position["collection"] == "Uniswap V3"
    assert position["fee_tier"] == 500
    assert position["in_range"] is True
    assert position["token0"]["symbol"] == "WETH"
    assert position["token0"]["amount"] == "0.1"
    assert position["token0"]["value_usd"] == "200.00"
    assert position["token1"]["symbol"] == "USDC"
    assert position["token1"]["amount"] == "200"
    assert position["value_usd"] == "400.00"
    row = application.state.db.fetchone(
        "SELECT * FROM contract_prices WHERE contract_address = ?", (WETH,)
    )
    assert row is not None
    assert row["price_usd"] == "2000"


def test_refresh_unpriced_position_marks_account_partial(app):
    application, client = app
    created = client.post(
        "/api/addresses", json={"chain": "ethereum", "address": OWNER, "tags": []}
    ).json()
    position = _sample_position(
        token1_address=SPAM, token1_symbol="SPAM", token1_decimals=18
    )
    _install_adapter(application, FakePositionAdapter([position]))
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))

    account = client.get(f"/api/addresses/{created['id']}").json()
    assert account["total_status"] == "partial"
    assert account["unpriced_position_count"] == 1
    assert account["positions"][0]["value_usd"] is None
    assert account["total_usd"] == "4000.00"
    assert "no price for SPAM" in (account["last_refresh_warning"] or "")


def test_refresh_replaces_saved_positions_after_a_complete_scan(app):
    application, client = app
    created = client.post(
        "/api/addresses", json={"chain": "ethereum", "address": OWNER, "tags": []}
    ).json()
    _install_adapter(application, FakePositionAdapter([_sample_position()]))
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))
    assert client.get(f"/api/addresses/{created['id']}").json()["position_count"] == 1

    _install_adapter(
        application, FakePositionAdapter([], complete_protocols={"uniswap-v3"})
    )
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))
    assert client.get(f"/api/addresses/{created['id']}").json()["position_count"] == 0


def test_refresh_keeps_saved_positions_when_scan_is_incomplete(app):
    application, client = app
    created = client.post(
        "/api/addresses", json={"chain": "ethereum", "address": OWNER, "tags": []}
    ).json()
    _install_adapter(application, FakePositionAdapter([_sample_position()]))
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))

    _install_adapter(application, FakePositionAdapter([], complete_protocols=set()))
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))
    account = client.get(f"/api/addresses/{created['id']}").json()
    assert account["position_count"] == 1
    assert account["total_usd"] == "4400.00"


def test_chain_metadata_reports_lp_support(client: TestClient):
    chains = {item["id"]: item for item in client.get("/api/chains").json()["items"]}
    assert chains["ethereum"]["supports_nft_positions"] is True
    assert chains["solana"]["supports_nft_positions"] is False
    assert chains["stacks"]["supports_nft_positions"] is False


def test_lp_collections_respect_settings_overrides():
    disabled = Settings(ethereum_lp_positions_enabled=False)
    assert lp_collections_for(disabled) == ()
    assert chain_meta("ethereum", disabled)["supports_nft_positions"] is False

    overridden = Settings(
        ethereum_lp_positions_enabled=True,
        ethereum_lp_position_managers="0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    )
    collections = lp_collections_for(overridden)
    assert len(collections) == 1
    assert collections[0].contract_address == UNISWAP_V3_POSITION_MANAGER

    # An invalid override falls back to the built-in collection instead of
    # silently disabling LP discovery.
    invalid = Settings(
        ethereum_lp_positions_enabled=True,
        ethereum_lp_position_managers="not-an-address",
    )
    assert lp_collections_for(invalid) == DEFAULT_NFT_COLLECTIONS


def test_schema_creates_lp_tables(work_dir):
    database = Database(work_dir / "schema.db")
    database.initialize()
    tables = {
        row["name"]
        for row in database.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"nft_positions", "contract_prices"} <= tables
    columns = {
        row["name"] for row in database.fetchall("PRAGMA table_info(nft_positions)")
    }
    assert {"token0_amount_raw", "token1_amount_raw", "value_usd", "in_range"} <= columns
    database.close()
