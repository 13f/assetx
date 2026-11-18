from __future__ import annotations

import asyncio

import httpx
import pytest

from app.chains.base import AllProvidersFailed, TokenNetwork
from app.chains.stacks import StacksAdapter
from app.db import Database
from app.seed import seed_database
from app.utils.c32 import (
    C32Error,
    decode_stacks_address,
    encode_stacks_address,
    normalize_stacks_address,
)
from app.utils.validation import (
    AddressValidationError,
    normalize_address,
    validate_contract_identifier,
)

ADDRESS = "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7"
ASSET_ID = "SP2DBFGMT7SATSJPCCA38SDDPBNNQ86QWADJ3E6WT.btc-v4::btc-v4"
SBTC_ASSET_ID = "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token"


def test_c32check_encode_decode_round_trip():
    payload = bytes.fromhex("a46ff88886c2ef9762d970b4d2c63678835bd39d")
    assert encode_stacks_address(22, payload) == ADDRESS

    version, decoded = decode_stacks_address(ADDRESS)
    assert version == 22
    assert decoded == payload
    assert decode_stacks_address(ADDRESS.lower()) == (22, payload)


def test_c32check_rejects_bad_checksums_and_extra_padding():
    with pytest.raises(C32Error, match="checksum"):
        decode_stacks_address("SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ8")
    with pytest.raises(C32Error, match="canonically"):
        decode_stacks_address("SP0" + ADDRESS[2:])


def test_stacks_normalizes_to_uppercase():
    assert normalize_stacks_address(ADDRESS.lower()) == ADDRESS


def test_stacks_address_validation():
    assert normalize_address("stacks", ADDRESS.lower()) == ADDRESS
    with pytest.raises(AddressValidationError, match="contract principal"):
        normalize_address("stacks", ADDRESS + ".my-contract")
    with pytest.raises(AddressValidationError):
        normalize_address("stacks", "not-a-stacks-address")


def test_stacks_contract_identifier_validation():
    assert validate_contract_identifier("stacks", ASSET_ID.lower()) == ASSET_ID
    assert validate_contract_identifier("stacks", SBTC_ASSET_ID) == SBTC_ASSET_ID
    with pytest.raises(AddressValidationError, match="full SIP-010 asset id"):
        validate_contract_identifier("stacks", "SP2DBFGMT7SATSJPCCA38SDDPBNNQ86QWADJ3E6WT.btc-v4")
    with pytest.raises(AddressValidationError, match="contract principal"):
        validate_contract_identifier("stacks", "btc-v4::btc-v4")


def _handler(payload: dict, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/extended/v1/address/" in request.url.path
        return httpx.Response(status_code, json=payload)

    return handler


def _networks() -> list[TokenNetwork]:
    return [
        TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True),
        TokenNetwork(
            2,
            10,
            "ALEX",
            "Alex Token",
            "stacks",
            "sp2j6zy48gv1ez5v2v5rb9mp66sw86pykknrv9ej7.alex-token::alex",
            8,
            False,
        ),
        TokenNetwork(3, 11, "MYSTERY", "Mystery", "stacks", None, 6, False),
    ]


def test_stacks_adapter_reads_native_and_sip010_balances():
    payload = {
        "stx": {"balance": "6550949"},
        "fungible_tokens": {
            "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7.alex-token::alex": {"balance": "20300000"},
            "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7.other::token": {"balance": "5"},
        },
    }

    async def run():
        transport = httpx.MockTransport(_handler(payload))
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks-one.invalid"], client)
            return await adapter.fetch_balances(ADDRESS, _networks())

    result = asyncio.run(run())
    assert result.provider == "stacks-one.invalid"
    assert result.balances == {1: "6550949", 2: "20300000", 3: "0"}
    assert result.warnings == ["MYSTERY: missing SIP-010 asset identifier"]


def test_stacks_adapter_reads_sbtc_balance():
    payload = {
        "stx": {"balance": "1264966"},
        "fungible_tokens": {
            SBTC_ASSET_ID: {"balance": "80863827638"},
            "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token-locked": {
                "balance": "1000"
            },
        },
    }

    async def run():
        transport = httpx.MockTransport(_handler(payload))
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks.invalid"], client)
            return await adapter.fetch_balances(
                "SPMN217717VVAC8VABB76PXX016FVHGDD87HVC6K",
                [
                    TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True),
                    TokenNetwork(2, 12, "SBTC", "sBTC", "stacks", SBTC_ASSET_ID, 8, False),
                ],
            )

    result = asyncio.run(run())
    assert result.balances == {1: "1264966", 2: "80863827638"}
    assert result.warnings == []


def test_stacks_adapter_returns_zero_for_unknown_address():
    async def run():
        transport = httpx.MockTransport(_handler({}, status_code=404))
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks.invalid"], client)
            return await adapter.fetch_balances(
                ADDRESS,
                [TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True)],
            )

    result = asyncio.run(run())
    assert result.balances == {1: "0"}
    assert result.warnings == []


def test_stacks_adapter_keeps_contract_names_case_sensitive():
    payload = {
        "stx": {"balance": "0"},
        "fungible_tokens": {
            "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7.Alex-Token::alex": {"balance": "100"},
        },
    }

    async def run():
        transport = httpx.MockTransport(_handler(payload))
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks.invalid"], client)
            return await adapter.fetch_balances(
                ADDRESS,
                [
                    TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True),
                    TokenNetwork(
                        2,
                        10,
                        "ALEX",
                        "Alex Token",
                        "stacks",
                        ADDRESS + ".alex-token::alex",
                        8,
                        False,
                    ),
                ],
            )

    result = asyncio.run(run())
    assert result.balances == {1: "0", 2: "0"}


def test_stacks_adapter_falls_back_to_next_provider():
    calls = {"count": 0}
    payload = {"stx": {"balance": "1000000"}, "fungible_tokens": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=payload)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks-one.invalid", "https://stacks-two.invalid"], client)
            return await adapter.fetch_balances(
                ADDRESS,
                [TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True)],
            )

    result = asyncio.run(run())
    assert calls["count"] == 2
    assert result.provider == "stacks-two.invalid"
    assert result.balances == {1: "1000000"}


def test_stacks_adapter_rejects_malformed_responses():
    responses = iter(
        [
            httpx.Response(200, json={"error": "rate limited"}),
            httpx.Response(200, json={"stx": {"balance": "1000000"}, "fungible_tokens": {}}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks-one.invalid", "https://stacks-two.invalid"], client)
            return await adapter.fetch_balances(
                ADDRESS,
                [TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True)],
            )

    result = asyncio.run(run())
    assert result.provider == "stacks-two.invalid"
    assert result.balances == {1: "1000000"}


def test_stacks_adapter_raises_when_every_provider_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            adapter = StacksAdapter(["https://stacks.invalid"], client)
            return await adapter.fetch_balances(
                ADDRESS,
                [TokenNetwork(1, 1, "STX", "Stacks", "stacks", None, 6, True)],
            )

    with pytest.raises(AllProvidersFailed):
        asyncio.run(run())


def test_seed_upgrade_adds_new_stacks_tokens_without_resurrecting_deleted_tokens(work_dir):
    db = Database(work_dir / "seed-upgrade.db")
    db.initialize()
    seed_database(db)
    assert db.fetchone("SELECT id FROM tokens WHERE symbol = 'STX'") is not None
    assert db.fetchone("SELECT id FROM tokens WHERE symbol = 'SBTC'") is not None

    # Simulate an AssetX 1.0 database (seed version 1) where the user deleted a
    # seeded token after the first run.
    db.execute("DELETE FROM tokens WHERE symbol IN ('STX', 'SBTC', 'USDT')")
    db.execute("UPDATE app_meta SET value = '1' WHERE key = 'seed_version'")

    seed_database(db)
    assert db.fetchone("SELECT id FROM tokens WHERE symbol = 'STX'") is not None
    assert db.fetchone("SELECT id FROM tokens WHERE symbol = 'SBTC'") is not None
    assert db.fetchone("SELECT id FROM tokens WHERE symbol = 'USDT'") is None
    version_row = db.fetchone("SELECT value FROM app_meta WHERE key = 'seed_version'")
    assert version_row["value"] == "4"

    seed_database(db)
    count = db.fetchone("SELECT COUNT(*) AS total FROM tokens WHERE symbol IN ('STX', 'SBTC')")
    assert count["total"] == 2
    db.close()
