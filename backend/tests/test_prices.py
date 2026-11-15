from __future__ import annotations

import asyncio

import httpx

from app.db import Database
from app.seed import seed_database
from app.services.prices import PriceService
from app.utils.time import utcnow_iso


def test_partial_price_cache_triggers_a_full_fetch(work_dir):
    db = Database(work_dir / "prices.db")
    db.initialize()
    seed_database(db)
    eth = db.fetchone("SELECT id FROM tokens WHERE symbol = 'ETH'")
    usdt = db.fetchone("SELECT id FROM tokens WHERE symbol = 'USDT'")
    assert eth and usdt
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO prices(token_id, price_usd, source, fetched_at) VALUES (?, '1', 'seed', ?)",
            (usdt["id"], utcnow_iso()),
        )

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "coins": {
                    "coingecko:ethereum": {"price": 2000.0},
                    "coingecko:tether": {"price": 1.0},
                }
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PriceService(db, client, cache_seconds=60)
            return await service.get_prices([eth["id"], usdt["id"]])

    result = asyncio.run(run())
    assert len(calls) == 1
    assert set(result.prices) == {eth["id"], usdt["id"]}
    assert result.source == "defillama"
    db.close()


def test_complete_price_cache_avoids_a_network_call(work_dir):
    db = Database(work_dir / "prices-complete.db")
    db.initialize()
    seed_database(db)
    rows = db.fetchall("SELECT id FROM tokens WHERE symbol IN ('ETH', 'USDT')")
    with db.transaction() as conn:
        for row in rows:
            conn.execute(
                "INSERT INTO prices(token_id, price_usd, source, fetched_at) VALUES (?, '1', 'cache', ?)",
                (row["id"], utcnow_iso()),
            )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network should not be called when the cache is complete")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PriceService(db, client, cache_seconds=60)
            return await service.get_prices([row["id"] for row in rows])

    result = asyncio.run(run())
    assert len(result.prices) == 2
    assert result.source == "cache"
    db.close()
