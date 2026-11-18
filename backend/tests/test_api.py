from __future__ import annotations

import time
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_and_meta(client: TestClient):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    chains = client.get("/api/chains").json()["items"]
    assert [item["id"] for item in chains] == [
        "ethereum",
        "solana",
        "bitcoin",
        "nervos",
        "cosmos",
        "stacks",
    ]
    symbols = {item["id"]: item["native_symbol"] for item in chains}
    assert symbols == {
        "ethereum": "ETH",
        "solana": "SOL",
        "bitcoin": "BTC",
        "nervos": "CKB",
        "cosmos": "ATOM",
        "stacks": "STX",
    }
    assert all(item["provider_count"] >= 2 for item in chains)
    stacks = next(item for item in chains if item["id"] == "stacks")
    assert stacks["token_standard"] == "SIP-010"
    assert stacks["native_coingecko_id"] == "blockstack"

    meta = client.get("/api/meta").json()
    assert {"STETH", "EARNETH"} <= set(meta["supported_tokens"])


def test_seeded_tokens(client: TestClient):
    tokens = client.get("/api/tokens").json()["items"]
    assert {token["symbol"] for token in tokens} == {
        "ETH",
        "SOL",
        "BTC",
        "CKB",
        "ATOM",
        "STX",
        "SBTC",
        "USDT",
        "USDC",
        "PAXG",
        "XAUT",
        "STETH",
        "EARNETH",
    }
    usdt = next(token for token in tokens if token["symbol"] == "USDT")
    assert {network["chain"] for network in usdt["networks"]} == {"ethereum", "solana"}
    stx = next(token for token in tokens if token["symbol"] == "STX")
    assert stx["coingecko_id"] == "blockstack"
    assert len(stx["networks"]) == 1
    stx_network = stx["networks"][0]
    assert stx_network["chain"] == "stacks"
    assert stx_network["is_native"] is True
    assert stx_network["contract_address"] is None
    assert stx_network["decimals"] == 6

    sbtc = next(token for token in tokens if token["symbol"] == "SBTC")
    assert sbtc["name"] == "sBTC"
    assert sbtc["coingecko_id"] == "sbtc-2"
    assert len(sbtc["networks"]) == 1
    sbtc_network = sbtc["networks"][0]
    assert sbtc_network["chain"] == "stacks"
    assert sbtc_network["is_native"] is False
    assert sbtc_network["contract_address"] == (
        "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token"
    )
    assert sbtc_network["decimals"] == 8

    steth = next(token for token in tokens if token["symbol"] == "STETH")
    assert steth["name"] == "Lido Staked Ether"
    assert steth["coingecko_id"] == "staked-ether"
    assert len(steth["networks"]) == 1
    steth_network = steth["networks"][0]
    assert steth_network["chain"] == "ethereum"
    assert steth_network["is_native"] is False
    assert steth_network["contract_address"] == (
        "0xae7ab96520de3a18e5e111b5eaab095312d7fe84"
    )
    assert steth_network["decimals"] == 18

    earneth = next(token for token in tokens if token["symbol"] == "EARNETH")
    assert earneth["name"] == "Lido Earn ETH"
    assert earneth["coingecko_id"] == "lido-earn-eth"
    assert len(earneth["networks"]) == 1
    earneth_network = earneth["networks"][0]
    assert earneth_network["chain"] == "ethereum"
    assert earneth_network["is_native"] is False
    assert earneth_network["contract_address"] == (
        "0xbbfc8683c8fe8cf73777fede7ab9574935fea0a4"
    )
    assert earneth_network["decimals"] == 18


def test_create_address_lowercases_tags_and_prevents_duplicates(client: TestClient):
    payload = {
        "chain": "ethereum",
        "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "tags": ["  DeFi  ", "Cold Wallet", "defi"],
    }
    response = client.post("/api/addresses", json=payload)
    assert response.status_code == 201
    account = response.json()
    assert account["address"] == payload["address"].lower()
    assert account["tags"] == ["defi", "cold wallet"]
    assert account["total_usd"] == "0.00"
    assert account["total_status"] == "stale"

    duplicate = client.post("/api/addresses", json=payload)
    assert duplicate.status_code == 409


def test_rejects_invalid_addresses(client: TestClient):
    for chain, address in [
        ("ethereum", "0x1234"),
        ("solana", "not-a-solana-address"),
        ("bitcoin", "not-a-bitcoin-address"),
        ("cosmos", "cosmos1invalid"),
        ("nervos", "ckb1invalid"),
        ("stacks", "SPinvalid"),
        ("stacks", "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7.my-contract"),
        ("stacks", "ST2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKQYAC0RQ"),
    ]:
        response = client.post("/api/addresses", json={"chain": chain, "address": address, "tags": []})
        assert response.status_code == 422, (chain, response.text)


def test_address_tag_filter(client: TestClient):
    created = client.post(
        "/api/addresses",
        json={
            "chain": "bitcoin",
            "address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "tags": ["Genesis"],
        },
    )
    assert created.status_code == 201
    filtered = client.get("/api/addresses", params={"tag": "genesis"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["tags"] == ["genesis"]

    updated = client.patch(
        f"/api/addresses/{created.json()['id']}",
        json={"tags": ["Satoshi", "HODL"]},
    )
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["satoshi", "hodl"]


def test_refresh_worker_saves_balances_and_prices(live_app):
    _application, client = live_app
    created = client.post(
        "/api/addresses",
        json={
            "chain": "ethereum",
            "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
            "tags": ["whale"],
        },
    )
    assert created.status_code == 201
    address_id = created.json()["id"]

    queued = client.post(f"/api/addresses/{address_id}/refresh")
    assert queued.status_code == 202
    assert queued.json()["job"]["status"] == "queued"

    deadline = time.time() + 10
    while time.time() < deadline:
        status = client.get("/api/refresh/status").json()
        if status["counts"]["queued"] == 0 and status["counts"]["running"] == 0:
            break
        time.sleep(0.05)

    account = client.get(f"/api/addresses/{address_id}").json()
    assert account["last_refreshed_at"] is not None
    assert account["last_refresh_error"] is None
    assert account["last_refresh_provider"] == "fake-rpc"
    assert account["total_usd"] == "4150.00"
    assert account["total_status"] == "complete"
    assert {token["symbol"] for token in account["tokens"]} == {"ETH", "USDT"}
    eth = next(token for token in account["tokens"] if token["symbol"] == "ETH")
    usdt = next(token for token in account["tokens"] if token["symbol"] == "USDT")
    assert Decimal(eth["balance"]) == Decimal("2")
    assert eth["price_usd"] == "2000"
    assert Decimal(usdt["balance"]) == Decimal("150")
    assert usdt["value_usd"] == "150.00"

    jobs = client.get("/api/refresh/jobs").json()["items"]
    assert jobs[0]["status"] == "success"
    assert jobs[0]["provider"] == "fake-rpc"


def test_refresh_queue_deduplicates(app):
    _application, client = app
    created = client.post(
        "/api/addresses",
        json={
            "chain": "ethereum",
            "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
            "tags": [],
        },
    ).json()
    first = client.post(f"/api/addresses/{created['id']}/refresh")
    assert first.status_code == 202
    second = client.post(f"/api/addresses/{created['id']}/refresh")
    assert second.status_code == 202
    assert second.json()["job"]["job_id"] == first.json()["job"]["job_id"]
    assert second.json()["job"]["deduplicated"] is True
    jobs = client.get("/api/refresh/jobs").json()["items"]
    assert len([job for job in jobs if job["status"] == "queued"]) == 1


def test_token_registry_crud(client: TestClient):
    created = client.post(
        "/api/tokens",
        json={"symbol": "link", "name": "Chainlink", "coingecko_id": "chainlink"},
    )
    assert created.status_code == 201
    token = created.json()
    assert token["symbol"] == "LINK"
    assert token["networks"] == []

    network = client.put(
        f"/api/tokens/{token['id']}/networks/ethereum",
        json={
            "contract_address": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
            "decimals": 18,
        },
    )
    assert network.status_code == 200
    assert network.json()["networks"][0]["contract_address"] == "0x514910771af9ca656af840dff83e8264ecf986ca"

    invalid = client.put(
        f"/api/tokens/{token['id']}/networks/solana",
        json={"contract_address": "not-a-mint", "decimals": 6},
    )
    assert invalid.status_code == 422

    stacks = client.put(
        f"/api/tokens/{token['id']}/networks/stacks",
        json={
            "contract_address": "sp2dbfgmt7satsjpcca38sddpbnnq86qwadj3e6wt.btc-v4::btc-v4",
            "decimals": 8,
        },
    )
    assert stacks.status_code == 200
    stacks_network = next(item for item in stacks.json()["networks"] if item["chain"] == "stacks")
    assert stacks_network["contract_address"] == (
        "SP2DBFGMT7SATSJPCCA38SDDPBNNQ86QWADJ3E6WT.btc-v4::btc-v4"
    )

    stacks_contract_only = client.put(
        f"/api/tokens/{token['id']}/networks/stacks",
        json={
            "contract_address": "SP2DBFGMT7SATSJPCCA38SDDPBNNQ86QWADJ3E6WT.btc-v4",
            "decimals": 8,
        },
    )
    assert stacks_contract_only.status_code == 422

    native_delete = client.delete("/api/tokens/1/networks/ethereum")
    assert native_delete.status_code == 409

    deleted = client.delete(f"/api/tokens/{token['id']}")
    assert deleted.status_code == 204
    assert all(item["symbol"] != "LINK" for item in client.get("/api/tokens").json()["items"])


def test_price_refresh_endpoint(client: TestClient):
    response = client.post("/api/tokens/prices/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["updated"] == 13
    assert body["source"] == "test"
    usdt = next(token for token in client.get("/api/tokens").json()["items"] if token["symbol"] == "USDT")
    assert usdt["price_usd"] == "1"
    assert usdt["price_source"] == "test"
