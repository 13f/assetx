from __future__ import annotations

from app.chains.registry import CHAIN_DEFINITIONS
from app.db import Database
from app.utils.time import utcnow_iso

SEED_VERSION = "1"

BUILTIN_TOKENS: list[dict] = [
    {
        "symbol": "ETH",
        "name": "Ether",
        "coingecko_id": "ethereum",
        "networks": [{"chain": "ethereum", "native": True, "decimals": 18}],
    },
    {
        "symbol": "SOL",
        "name": "Solana",
        "coingecko_id": "solana",
        "networks": [{"chain": "solana", "native": True, "decimals": 9}],
    },
    {
        "symbol": "BTC",
        "name": "Bitcoin",
        "coingecko_id": "bitcoin",
        "networks": [{"chain": "bitcoin", "native": True, "decimals": 8}],
    },
    {
        "symbol": "CKB",
        "name": "Nervos Network",
        "coingecko_id": "nervos-network",
        "networks": [{"chain": "nervos", "native": True, "decimals": 8}],
    },
    {
        "symbol": "ATOM",
        "name": "Cosmos Hub",
        "coingecko_id": "cosmos",
        "networks": [{"chain": "cosmos", "native": True, "decimals": 6}],
    },
    {
        "symbol": "USDT",
        "name": "Tether USD",
        "coingecko_id": "tether",
        "networks": [
            {
                "chain": "ethereum",
                "contract": "0xdac17f958d2ee523a2206206994597c13d831ec7",
                "decimals": 6,
            },
            {
                "chain": "solana",
                "contract": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                "decimals": 6,
            },
        ],
    },
    {
        "symbol": "USDC",
        "name": "USD Coin",
        "coingecko_id": "usd-coin",
        "networks": [
            {
                "chain": "ethereum",
                "contract": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
                "decimals": 6,
            },
            {
                "chain": "solana",
                "contract": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "decimals": 6,
            },
        ],
    },
    {
        "symbol": "PAXG",
        "name": "PAX Gold",
        "coingecko_id": "pax-gold",
        "networks": [
            {
                "chain": "ethereum",
                "contract": "0x45804880de22913dafe09f4980848ece6ecbaf78",
                "decimals": 18,
            }
        ],
    },
    {
        "symbol": "XAUT",
        "name": "Tether Gold",
        "coingecko_id": "tether-gold",
        "networks": [
            {
                "chain": "ethereum",
                "contract": "0x68749665ff8d2d112fa859aa293f07a622782f38",
                "decimals": 6,
            }
        ],
    },
]


def seed_database(db: Database) -> None:
    existing = db.fetchone("SELECT value FROM app_meta WHERE key = 'seed_version'")
    if existing is not None:
        return
    timestamp = utcnow_iso()
    with db.transaction() as conn:
        for token in BUILTIN_TOKENS:
            conn.execute(
                "INSERT OR IGNORE INTO tokens(symbol, name, coingecko_id, created_at) VALUES (?, ?, ?, ?)",
                (token["symbol"], token["name"], token["coingecko_id"], timestamp),
            )
            row = conn.execute("SELECT id FROM tokens WHERE symbol = ?", (token["symbol"],)).fetchone()
            if row is None:
                continue
            token_id = row["id"]
            for network in token["networks"]:
                chain = network["chain"]
                if chain not in CHAIN_DEFINITIONS:
                    continue
                native = bool(network.get("native"))
                conn.execute(
                    """
                    INSERT OR IGNORE INTO token_networks
                        (token_id, chain, contract_address, decimals, is_native, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        token_id,
                        chain,
                        network.get("contract"),
                        network["decimals"],
                        1 if native else 0,
                        timestamp,
                        timestamp,
                    ),
                )
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES ('seed_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SEED_VERSION,),
        )
