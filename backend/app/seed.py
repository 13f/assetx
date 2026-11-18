from __future__ import annotations

import sqlite3

from app.chains.registry import CHAIN_DEFINITIONS
from app.db import Database
from app.utils.time import utcnow_iso

# Bump this when adding a new step to SEED_STEPS. Existing databases receive
# only the steps they have not seen yet.
SEED_VERSION = 4

# Seed data is versioned so an upgrade can add a new built-in token without
# resurrecting tokens the user deleted from the registry.
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

# Version 2 adds Stacks support (native STX).
STACKS_TOKENS: list[dict] = [
    {
        "symbol": "STX",
        "name": "Stacks",
        "coingecko_id": "blockstack",
        "networks": [{"chain": "stacks", "native": True, "decimals": 6}],
    },
]

# Version 3 adds the canonical sBTC SIP-010 asset on Stacks.
SBTC_TOKENS: list[dict] = [
    {
        "symbol": "SBTC",
        "name": "sBTC",
        "coingecko_id": "sbtc-2",
        "networks": [
            {
                "chain": "stacks",
                "contract": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token",
                "decimals": 8,
            }
        ],
    },
]

# Version 4 adds Lido assets on Ethereum. stETH is a rebasing ERC-20 whose
# balanceOf() already includes accrued staking rewards. earnETH is the Lido
# Earn ETH vault share token (the ShareManager ERC-20, not the vault contract):
# the wallet holds a fixed number of shares and the per-share value tracks the
# vault's ETH-denominated NAV. Both are ordinary ERC-20 balances for the
# Ethereum adapter; only their price semantics differ.
LIDO_TOKENS: list[dict] = [
    {
        "symbol": "STETH",
        "name": "Lido Staked Ether",
        "coingecko_id": "staked-ether",
        "networks": [
            {
                "chain": "ethereum",
                "contract": "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
                "decimals": 18,
            }
        ],
    },
    {
        "symbol": "EARNETH",
        "name": "Lido Earn ETH",
        "coingecko_id": "lido-earn-eth",
        "networks": [
            {
                "chain": "ethereum",
                "contract": "0xbbfc8683c8fe8cf73777fede7ab9574935fea0a4",
                "decimals": 18,
            }
        ],
    },
]

SEED_STEPS: dict[int, list[dict]] = {
    1: BUILTIN_TOKENS,
    2: STACKS_TOKENS,
    3: SBTC_TOKENS,
    4: LIDO_TOKENS,
}


def _current_seed_version(db: Database) -> int:
    row = db.fetchone("SELECT value FROM app_meta WHERE key = 'seed_version'")
    if row is None:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def _insert_token(conn: sqlite3.Connection, token: dict, timestamp: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO tokens(symbol, name, coingecko_id, created_at) VALUES (?, ?, ?, ?)",
        (token["symbol"], token["name"], token["coingecko_id"], timestamp),
    )
    row = conn.execute("SELECT id FROM tokens WHERE symbol = ?", (token["symbol"],)).fetchone()
    if row is None:
        return
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


def seed_database(db: Database) -> None:
    current = _current_seed_version(db)
    if current >= SEED_VERSION:
        return
    timestamp = utcnow_iso()
    with db.transaction() as conn:
        for version in sorted(SEED_STEPS):
            if version <= current:
                continue
            for token in SEED_STEPS[version]:
                _insert_token(conn, token, timestamp)
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES ('seed_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SEED_VERSION),),
        )
