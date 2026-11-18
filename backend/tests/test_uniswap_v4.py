from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.chains.base import FetchResult, LpPosition, ProviderError, TokenNetwork
from app.chains.blockscout import BlockscoutClient
from app.chains.ethereum import EthereumAdapter
from app.chains.uniswap import (
    DEFAULT_NFT_COLLECTIONS,
    NATIVE_CURRENCY,
    SEL_DECIMALS,
    SEL_GET_POOL_AND_POSITION_INFO,
    SEL_GET_POSITION_LIQUIDITY,
    SEL_OWNER_OF,
    SEL_SYMBOL,
    SEL_V4_GET_SLOT0,
    UNISWAP_V4_POSITION_MANAGER,
    UNISWAP_V4_STATE_VIEW,
    RpcTransport,
    UniswapV4Reader,
    encode_pool_key,
    pool_id_for_key,
    position_amounts,
    sqrt_ratio_at_tick,
)
from app.utils.keccak import keccak256, selector

OWNER = "0x89154ea9be8e0f1dcc0c659d4e439438318f2950"
WBTC = "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
NFPM_V3 = "0xc36442b4a4522e871399cd717abdd847ab11fe88"
TOKEN_ID = "510857"
KEY = (NATIVE_CURRENCY, WBTC, 500, 10, NATIVE_CURRENCY)
POOL_ID = "0x599326d9cd5e1ea0893305c87d5ec3199e7f05e94d72159f35dea381479a615e"
SQRT_PRICE = 132570300837579214248011
CURRENT_TICK = -266028
LIQUIDITY = 3776602649175
TICK_LOWER = -273700
TICK_UPPER = -257450
AMOUNT0 = 787150788145499930
AMOUNT1 = 2013241

ERROR = object()


def word(value: int) -> str:
    return f"{value & ((1 << 256) - 1):064x}"


def address_word(address: str) -> str:
    return f"{int(address, 16):064x}"


def packed_position_info(
    pool_id: str,
    tick_lower: int,
    tick_upper: int,
    has_subscriber: int = 0,
) -> int:
    truncated = int(pool_id, 16) >> 56
    return (
        (truncated << 56)
        | ((tick_upper & 0xFFFFFF) << 32)
        | ((tick_lower & 0xFFFFFF) << 8)
        | has_subscriber
    )


def pool_info_response(
    key: tuple[str, str, int, int, str] = KEY,
    tick_lower: int = TICK_LOWER,
    tick_upper: int = TICK_UPPER,
) -> str:
    pool_id = pool_id_for_key(key)
    words = [
        int(key[0], 16),
        int(key[1], 16),
        key[2],
        key[3],
        int(key[4], 16),
        packed_position_info(pool_id, tick_lower, tick_upper),
    ]
    return "0x" + "".join(word(value) for value in words)


def slot0_response(
    sqrt_price: int = SQRT_PRICE,
    tick: int = CURRENT_TICK,
    lp_fee: int = 500,
) -> str:
    return "0x" + word(sqrt_price) + word(tick) + word(0) + word(lp_fee)


def encode_string(text: str) -> str:
    raw = text.encode()
    padded = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return "0x" + word(32) + word(len(raw)) + padded.hex()


def v4_rpc_handler(
    *,
    token_id: str = TOKEN_ID,
    key: tuple[str, str, int, int, str] = KEY,
    liquidity: int = LIQUIDITY,
    owner: str = OWNER,
    current_tick: int = CURRENT_TICK,
    sqrt_price: int = SQRT_PRICE,
    fail_pool_info: bool = False,
    fail_liquidity: bool = False,
    fail_slot0: bool = False,
    fail_decimals: bool = False,
    requests_seen: list[dict] | None = None,
    items: list[dict] | None = None,
    blockscout_status: int = 200,
):
    """Serve both Blockscout GETs and Ethereum JSON-RPC POSTs."""

    def dispatch_rpc(to: str, data: str):
        if to == UNISWAP_V4_POSITION_MANAGER:
            if data.startswith(SEL_GET_POOL_AND_POSITION_INFO):
                return ERROR if fail_pool_info else pool_info_response(key)
            if data.startswith(SEL_GET_POSITION_LIQUIDITY):
                return ERROR if fail_liquidity else "0x" + word(liquidity)
            if data.startswith(SEL_OWNER_OF):
                return "0x" + address_word(owner)
        if to == UNISWAP_V4_STATE_VIEW and data.startswith(SEL_V4_GET_SLOT0):
            return ERROR if fail_slot0 else slot0_response(
                sqrt_price=sqrt_price, tick=current_tick
            )
        if to == WBTC:
            if data.startswith(SEL_SYMBOL):
                return encode_string("WBTC")
            if data.startswith(SEL_DECIMALS):
                return ERROR if fail_decimals else "0x" + word(8)
        if to == NFPM_V3:
            if data.startswith("0x70a08231"):
                return "0x" + word(0)
        return ERROR

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if blockscout_status != 200:
                return httpx.Response(blockscout_status, text="unavailable")
            return httpx.Response(
                200,
                json={
                    "items": items
                    if items is not None
                    else [
                        {
                            "id": token_id,
                            "token": {
                                "address_hash": "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e",
                                "type": "ERC-721",
                            },
                        }
                    ],
                    "next_page_params": None,
                },
            )
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
                result = dispatch_rpc(params["to"].lower(), params["data"])
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


def run_v4_reader(handler, token_ids: list[str] | None = None, owner: str = OWNER):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            reader = UniswapV4Reader(RpcTransport(client, "https://rpc.invalid"))
            return await reader.read(
                owner, [TOKEN_ID] if token_ids is None else token_ids
            )

    return asyncio.run(run())


# ---------------------------------------------------------------------------
# Keccak and encoding
# ---------------------------------------------------------------------------


def test_keccak_vectors_and_v4_selectors():
    assert keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert keccak256(b"abc").hex() == (
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"
    )
    assert selector("getPoolAndPositionInfo(uint256)") == SEL_GET_POOL_AND_POSITION_INFO
    assert selector("getPositionLiquidity(uint256)") == SEL_GET_POSITION_LIQUIDITY
    assert selector("getSlot0(bytes32)") == SEL_V4_GET_SLOT0
    assert selector("ownerOf(uint256)") == SEL_OWNER_OF


def test_v4_pool_id_matches_onchain_value():
    assert pool_id_for_key(KEY) == POOL_ID
    encoded = encode_pool_key(KEY)
    assert len(encoded) == 160
    assert encoded[:32] == b"\x00" * 32  # native currency0


def test_blockscout_treats_an_unindexed_address_as_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            blockscout = BlockscoutClient(client, ["https://bs.invalid"])
            return await blockscout.erc721_token_ids(
                OWNER, UNISWAP_V4_POSITION_MANAGER
            )

    assert asyncio.run(run()) == []


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def test_v4_reader_decodes_a_position():
    positions, warnings, complete = run_v4_reader(v4_rpc_handler())
    assert warnings == []
    assert complete is True
    assert len(positions) == 1
    position = positions[0]
    assert position.protocol == "uniswap-v4"
    assert position.collection == "Uniswap V4"
    assert position.contract_address == UNISWAP_V4_POSITION_MANAGER
    assert position.token_id == TOKEN_ID
    assert position.pool_address == POOL_ID
    assert position.token0_address == NATIVE_CURRENCY
    assert position.token0_symbol == "ETH"
    assert position.token0_decimals == 18
    assert position.token0_amount_raw == str(AMOUNT0)
    assert position.token1_address == WBTC
    assert position.token1_symbol == "WBTC"
    assert position.token1_decimals == 8
    assert position.token1_amount_raw == str(AMOUNT1)
    assert position.fee_tier == 500
    assert (position.tick_lower, position.tick_upper) == (TICK_LOWER, TICK_UPPER)
    assert position.in_range is True
    # Cross-check against the shared concentrated-liquidity math.
    assert position_amounts(LIQUIDITY, SQRT_PRICE, TICK_LOWER, TICK_UPPER) == (
        AMOUNT0,
        AMOUNT1,
    )


def test_v4_reader_marks_out_of_range():
    positions, warnings, complete = run_v4_reader(
        v4_rpc_handler(
            current_tick=TICK_UPPER + 1,
            sqrt_price=sqrt_ratio_at_tick(TICK_UPPER + 1),
        )
    )
    assert warnings == []
    assert complete is True
    assert positions[0].in_range is False
    assert int(positions[0].token0_amount_raw) == 0
    assert int(positions[0].token1_amount_raw) > 0


def test_v4_reader_skips_positions_no_longer_owned():
    positions, warnings, complete = run_v4_reader(
        v4_rpc_handler(owner="0x0000000000000000000000000000000000000001")
    )
    assert positions == []
    assert complete is True
    assert any("no longer owned" in warning for warning in warnings)


def test_v4_reader_raises_when_every_position_fails():
    with pytest.raises(ProviderError):
        run_v4_reader(v4_rpc_handler(fail_liquidity=True))


def test_v4_reader_requires_token_metadata():
    positions, warnings, complete = run_v4_reader(v4_rpc_handler(fail_decimals=True))
    assert positions == []
    assert complete is False
    assert any("token metadata unavailable" in warning for warning in warnings)


def test_v4_reader_returns_nothing_without_token_ids():
    positions, warnings, complete = run_v4_reader(
        v4_rpc_handler(), token_ids=[]
    )
    assert positions == []
    assert warnings == []
    assert complete is True


# ---------------------------------------------------------------------------
# Blockscout discovery
# ---------------------------------------------------------------------------


def test_blockscout_filters_by_contract_and_token_id():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "510857",
                        "token": {
                            "address_hash": "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e"
                        },
                    },
                    {
                        "id": "42",
                        "token": {
                            "address_hash": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
                        },
                    },
                    {
                        "id": "not-a-number",
                        "token": {
                            "address_hash": "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e"
                        },
                    },
                ],
                "next_page_params": None,
            },
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            blockscout = BlockscoutClient(client, ["https://bs.invalid"])
            return await blockscout.erc721_token_ids(
                OWNER, UNISWAP_V4_POSITION_MANAGER, limit=10
            )

    ids = asyncio.run(run())
    assert ids == ["510857"]
    assert seen[0].url.path == f"/api/v2/addresses/{OWNER}/nft"
    assert seen[0].url.params.get("type") == "ERC-721"


def test_blockscout_paginates():
    pages = {
        None: {
            "items": [
                {
                    "id": "1",
                    "token": {
                        "address_hash": "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e"
                    },
                }
            ],
            "next_page_params": {"block_number": 100, "index": 2},
        },
        "2": {
            "items": [
                {
                    "id": "2",
                    "token": {
                        "address_hash": "0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e"
                    },
                }
            ],
            "next_page_params": None,
        },
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("index")])

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            blockscout = BlockscoutClient(client, ["https://bs.invalid"])
            return await blockscout.erc721_token_ids(
                OWNER, UNISWAP_V4_POSITION_MANAGER, limit=10
            )

    assert asyncio.run(run()) == ["1", "2"]
    assert len(requests) == 2


def test_blockscout_falls_back_to_next_endpoint():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "one.invalid":
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"items": [], "next_page_params": None})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            blockscout = BlockscoutClient(client, ["https://one.invalid", "https://two.invalid"])
            return await blockscout.erc721_token_ids(
                OWNER, UNISWAP_V4_POSITION_MANAGER
            )

    assert asyncio.run(run()) == []
    assert calls == ["one.invalid", "two.invalid"]


def test_blockscout_raises_when_every_endpoint_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            blockscout = BlockscoutClient(client, ["https://bs.invalid"])
            return await blockscout.erc721_token_ids(
                OWNER, UNISWAP_V4_POSITION_MANAGER
            )

    with pytest.raises(ProviderError):
        asyncio.run(run())


# ---------------------------------------------------------------------------
# Ethereum adapter integration
# ---------------------------------------------------------------------------


def _networks() -> list[TokenNetwork]:
    return [
        TokenNetwork(1, 1, "ETH", "Ether", "ethereum", None, 18, True),
        TokenNetwork(2, 6, "USDC", "USD Coin", "ethereum", USDC, 6, False),
    ]


def _run_adapter(handler, *, v4: bool = True):
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = EthereumAdapter(
                ["https://rpc.invalid"],
                client,
                lp_collections=DEFAULT_NFT_COLLECTIONS,
                lp_v4_enabled=v4,
                lp_v4_blockscout_apis=["https://bs.invalid"],
            )
            return await adapter.fetch_balances(OWNER, _networks())

    return asyncio.run(run())


def test_ethereum_adapter_combines_v3_and_v4():
    result = _run_adapter(v4_rpc_handler())
    assert result.positions_complete == {"uniswap-v3", "uniswap-v4"}
    assert [position.protocol for position in result.positions] == ["uniswap-v4"]
    assert result.positions[0].token_id == TOKEN_ID


def test_ethereum_adapter_keeps_v3_complete_when_v4_discovery_fails():
    result = _run_adapter(v4_rpc_handler(blockscout_status=500))
    assert result.positions_complete == {"uniswap-v3"}
    assert result.positions == []
    assert any("Uniswap V4" in warning for warning in result.warnings)


def test_ethereum_adapter_can_disable_v4():
    result = _run_adapter(v4_rpc_handler(), v4=False)
    assert result.positions_complete == {"uniswap-v3"}
    assert result.positions == []


# ---------------------------------------------------------------------------
# Refresh persistence and native pricing
# ---------------------------------------------------------------------------


def _v4_position(
    token_id: str = TOKEN_ID,
    token0_amount_raw: str = str(AMOUNT0),
    token1_amount_raw: str = str(AMOUNT1),
) -> LpPosition:
    return LpPosition(
        protocol="uniswap-v4",
        collection="Uniswap V4",
        contract_address=UNISWAP_V4_POSITION_MANAGER,
        token_id=token_id,
        pool_address=POOL_ID,
        token0_address=NATIVE_CURRENCY,
        token0_symbol="ETH",
        token0_decimals=18,
        token0_amount_raw=token0_amount_raw,
        token1_address=WBTC,
        token1_symbol="WBTC",
        token1_decimals=8,
        token1_amount_raw=token1_amount_raw,
        fee_tier=500,
        tick_lower=TICK_LOWER,
        tick_upper=TICK_UPPER,
        liquidity=str(LIQUIDITY),
        in_range=True,
    )


class V4FakeAdapter:
    chain = "ethereum"
    providers = ["https://fake-rpc.invalid"]

    def __init__(self, positions: list[LpPosition], complete: set[str] | None = None):
        self.positions = positions
        self.complete = (
            {position.protocol for position in positions}
            if complete is None
            else set(complete)
        )

    async def fetch_balances(
        self, address: str, networks: list[TokenNetwork]
    ) -> FetchResult:
        return FetchResult(
            balances={
                network.id: (
                    str(2 * 10**network.decimals) if network.is_native else "0"
                )
                for network in networks
            },
            provider="fake-rpc",
            positions=list(self.positions),
            positions_complete=set(self.complete),
        )


def _install(application, adapter) -> None:
    application.state.adapters["ethereum"] = adapter
    application.state.refresh_service.adapters["ethereum"] = adapter


def test_refresh_values_v4_native_eth_and_persists(app):
    application, client = app
    created = client.post(
        "/api/addresses", json={"chain": "ethereum", "address": OWNER, "tags": []}
    ).json()
    _install(application, V4FakeAdapter([_v4_position()]))
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))

    account = client.get(f"/api/addresses/{created['id']}").json()
    assert account["position_count"] == 1
    position = account["positions"][0]
    assert position["protocol"] == "uniswap-v4"
    assert position["collection"] == "Uniswap V4"
    assert position["token0"]["symbol"] == "ETH"
    assert position["token0"]["price_usd"] == "2000"
    assert position["token0"]["value_usd"] == "1574.30"
    assert position["token1"]["symbol"] == "WBTC"
    assert position["token1"]["price_usd"] == "60000"
    assert position["token1"]["value_usd"] == "1207.94"
    # 0.78715078814549993 ETH at 2000 plus 0.02013241 WBTC at 60000.
    assert position["value_usd"] == "2782.25"
    # 2 ETH at 2000 plus the position value.
    assert account["total_usd"] == "6782.25"
    assert account["total_status"] == "complete"


def test_refresh_replaces_only_completed_protocols(app):
    application, client = app
    created = client.post(
        "/api/addresses", json={"chain": "ethereum", "address": OWNER, "tags": []}
    ).json()
    v3_position = _v3_like_position()
    _install(
        application,
        V4FakeAdapter([v3_position, _v4_position()], complete={"uniswap-v3", "uniswap-v4"}),
    )
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))
    account = client.get(f"/api/addresses/{created['id']}").json()
    assert {item["protocol"] for item in account["positions"]} == {
        "uniswap-v3",
        "uniswap-v4",
    }

    # Only V4 is scanned this time and it has no positions: V4 rows go away,
    # the previously saved V3 row is preserved because its scan did not run.
    _install(application, V4FakeAdapter([], complete={"uniswap-v4"}))
    asyncio.run(application.state.refresh_service.refresh_address(created["id"]))
    account = client.get(f"/api/addresses/{created['id']}").json()
    assert [item["protocol"] for item in account["positions"]] == ["uniswap-v3"]


def _v3_like_position() -> LpPosition:
    return LpPosition(
        protocol="uniswap-v3",
        collection="Uniswap V3",
        contract_address=NFPM_V3,
        token_id="42",
        pool_address="0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
        token0_address="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        token0_symbol="WETH",
        token0_decimals=18,
        token0_amount_raw=str(10**17),
        token1_address=USDC,
        token1_symbol="USDC",
        token1_decimals=6,
        token1_amount_raw=str(200 * 10**6),
        fee_tier=500,
        tick_lower=-887220,
        tick_upper=887220,
        liquidity="1",
        in_range=True,
    )
