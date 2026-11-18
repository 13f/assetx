from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.chains.base import TokenNetwork
from app.chains.ethereum import EthereumAdapter
from app.chains.solana import SolanaAdapter
from app.db import Database
from app.services.queue import RefreshQueue
from app.utils.ckb import decode_ckb_lock
from app.utils.validation import AddressValidationError, normalize_address


@pytest.mark.parametrize(
    ("chain", "address", "expected"),
    [
        (
            "ethereum",
            "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
            "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
        ),
        (
            "solana",
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        ),
        (
            "bitcoin",
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        ),
        (
            "bitcoin",
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        ),
        (
            "cosmos",
            "cosmos1q4hjnwuat6zuxuplew5rvvw6yw3a4kwrm3e5ds",
            "cosmos1q4hjnwuat6zuxuplew5rvvw6yw3a4kwrm3e5ds",
        ),
        (
            "nervos",
            "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqdnnw7qkdnnclfkg59uzn8umtfd2kwxceqxwquc4",
            "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqdnnw7qkdnnclfkg59uzn8umtfd2kwxceqxwquc4",
        ),
        (
            "stacks",
            "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7",
            "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7",
        ),
        (
            "stacks",
            "sp2j6zy48gv1ez5v2v5rb9mp66sw86pykknrv9ej7",
            "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7",
        ),
        (
            "stacks",
            "SM2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKQVX8X0G",
            "SM2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKQVX8X0G",
        ),
        (
            "stacks",
            "SP000000000000000000002Q6VF78",
            "SP000000000000000000002Q6VF78",
        ),
    ],
)
def test_valid_addresses(chain: str, address: str, expected: str):
    assert normalize_address(chain, address) == expected


def test_ckb_short_address_decodes():
    lock = decode_ckb_lock("ckb1qyqt8xaupvm8837nv3gtc9x0ekkj64vud3jqfwyw5v")
    assert lock.hash_type == "type"
    assert lock.args.startswith("0x")
    assert len(lock.args) == 42


@pytest.mark.parametrize(
    ("chain", "address"),
    [
        ("ethereum", "0x1234"),
        ("solana", "1111111111111111111111111111111"),
        ("bitcoin", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080"),
        ("cosmos", "cosmos1q4hjnwuat6zuxuplew5rvvw6yw3a4kwrm3e5d"),
        ("nervos", "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqdnnw7qkdnnclfkg59uzn8umtfd2kwxceqxwquc5"),
        ("stacks", "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ8"),
        ("stacks", "ST2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKQYAC0RQ"),
        ("stacks", "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7.my-contract"),
        ("stacks", "SP"),
    ],
)
def test_invalid_addresses(chain: str, address: str):
    with pytest.raises(AddressValidationError):
        normalize_address(chain, address)


def test_ethereum_adapter_falls_back_to_next_rpc():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": "native", "result": "0xde0b6b3a7640000"},
                {"jsonrpc": "2.0", "id": "token:2", "result": "0x" + format(150_000000, "x")},
            ],
        )

    networks = [
        TokenNetwork(1, 1, "ETH", "Ether", "ethereum", None, 18, True),
        TokenNetwork(2, 6, "USDT", "Tether", "ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7", 6, False),
    ]

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = EthereumAdapter(["https://rpc-one.invalid", "https://rpc-two.invalid"], client)
            return await adapter.fetch_balances("0xd8da6bf26964af9d7eed9e03e53415d37aa96045", networks)

    result = asyncio.run(run())
    assert calls["count"] == 2
    assert result.provider == "rpc-two.invalid"
    assert result.balances[1] == "1000000000000000000"
    assert result.balances[2] == "150000000"


def test_solana_adapter_reads_native_and_spl_balances():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        method = "getTokenAccountsByOwner" if "getTokenAccountsByOwner" in body else "getBalance"
        if method == "getBalance":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 1}, "value": 2_000_000_000}},
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "context": {"slot": 1},
                    "value": [
                        {
                            "account": {
                                "data": {
                                    "parsed": {
                                        "info": {"tokenAmount": {"amount": "150000000", "decimals": 6}}
                                    }
                                }
                            }
                        }
                    ],
                },
            },
        )

    networks = [
        TokenNetwork(1, 2, "SOL", "Solana", "solana", None, 9, True),
        TokenNetwork(
            2,
            6,
            "USDT",
            "Tether",
            "solana",
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            6,
            False,
        ),
    ]

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = SolanaAdapter(["https://solana.invalid"], client)
            return await adapter.fetch_balances(
                "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM", networks
            )

    result = asyncio.run(run())
    assert result.balances == {1: "2000000000", 2: "150000000"}
    assert result.warnings == []


def test_refresh_queue_waits_between_addresses(work_dir):
    db = Database(work_dir / "queue.db")
    db.initialize()
    queue = RefreshQueue(db, None, interval_seconds=0.05)  # type: ignore[arg-type]
    queue._last_started = time.monotonic()
    started = time.monotonic()
    asyncio.run(queue._wait_for_slot())
    assert time.monotonic() - started >= 0.04
    db.close()
