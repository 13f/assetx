from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from app.chains.base import TokenNetwork
from app.chains.registry import CHAIN_DEFINITIONS
from app.db import Database
from app.utils.amounts import amount_from_raw, decimal_to_str, format_price, format_usd


def load_networks(
    db: Database,
    chain: str | None = None,
    token_id: int | None = None,
    enabled_only: bool = True,
) -> list[TokenNetwork]:
    clauses: list[str] = []
    params: list[object] = []
    if chain:
        clauses.append("tn.chain = ?")
        params.append(chain)
    if token_id is not None:
        clauses.append("tn.token_id = ?")
        params.append(token_id)
    if enabled_only:
        clauses.append("tn.enabled = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.fetchall(
        f"""
        SELECT tn.id, tn.token_id, tn.chain, tn.contract_address, tn.decimals,
               tn.is_native, t.symbol, t.name, t.coingecko_id
        FROM token_networks tn
        JOIN tokens t ON t.id = tn.token_id
        {where}
        ORDER BY t.symbol COLLATE NOCASE, tn.chain
        """,
        tuple(params),
    )
    return [
        TokenNetwork(
            id=row["id"],
            token_id=row["token_id"],
            symbol=row["symbol"],
            name=row["name"],
            chain=row["chain"],
            contract_address=row["contract_address"],
            decimals=row["decimals"],
            is_native=bool(row["is_native"]),
            coingecko_id=row["coingecko_id"],
        )
        for row in rows
    ]


def get_address(db: Database, address_id: int):
    return db.fetchone("SELECT * FROM addresses WHERE id = ?", (address_id,))


def get_address_by_value(db: Database, chain: str, address: str):
    return db.fetchone(
        "SELECT * FROM addresses WHERE chain = ? AND address = ?",
        (chain, address),
    )


def list_address_rows(db: Database) -> list:
    return db.fetchall("SELECT * FROM addresses ORDER BY id DESC")


def active_job_for_address(db: Database, address_id: int):
    return db.fetchone(
        """
        SELECT id, status, created_at, started_at, warning, error
        FROM refresh_jobs
        WHERE address_id = ? AND status IN ('queued', 'running')
        ORDER BY id DESC LIMIT 1
        """,
        (address_id,),
    )


def balances_for_address(db: Database, address_id: int) -> list:
    return db.fetchall(
        """
        SELECT b.raw_balance, b.price_usd, b.value_usd, b.updated_at,
               tn.id AS network_id, tn.chain, tn.contract_address, tn.decimals, tn.is_native,
               t.id AS token_id, t.symbol, t.name, t.coingecko_id
        FROM balances b
        JOIN token_networks tn ON tn.id = b.token_network_id
        JOIN tokens t ON t.id = tn.token_id
        WHERE b.address_id = ?
        ORDER BY t.symbol COLLATE NOCASE
        """,
        (address_id,),
    )


def positions_for_address(db: Database, address_id: int) -> list:
    return db.fetchall(
        "SELECT * FROM nft_positions WHERE address_id = ? ORDER BY id",
        (address_id,),
    )


def _balance_dict(row) -> dict[str, Any]:
    balance = amount_from_raw(row["raw_balance"], row["decimals"])
    value = Decimal(row["value_usd"]) if row["value_usd"] is not None else None
    return {
        "network_id": row["network_id"],
        "token_id": row["token_id"],
        "symbol": row["symbol"],
        "name": row["name"],
        "chain": row["chain"],
        "contract_address": row["contract_address"],
        "decimals": row["decimals"],
        "is_native": bool(row["is_native"]),
        "raw_balance": row["raw_balance"],
        "balance": decimal_to_str(balance),
        "price_usd": format_price(Decimal(row["price_usd"])) if row["price_usd"] is not None else None,
        "value_usd": format_usd(value),
        "updated_at": row["updated_at"],
    }


def _nft_position_dict(row) -> dict[str, Any]:
    amount0 = amount_from_raw(row["token0_amount_raw"], row["token0_decimals"])
    amount1 = amount_from_raw(row["token1_amount_raw"], row["token1_decimals"])
    price0 = Decimal(row["token0_price_usd"]) if row["token0_price_usd"] is not None else None
    price1 = Decimal(row["token1_price_usd"]) if row["token1_price_usd"] is not None else None
    value = Decimal(row["value_usd"]) if row["value_usd"] is not None else None
    return {
        "id": row["id"],
        "protocol": row["protocol"],
        "collection": row["collection"],
        "contract_address": row["contract_address"],
        "token_id": row["token_id"],
        "pool_address": row["pool_address"],
        "fee_tier": row["fee_tier"],
        "tick_lower": row["tick_lower"],
        "tick_upper": row["tick_upper"],
        "in_range": bool(row["in_range"]),
        "liquidity": row["liquidity"],
        "token0": {
            "address": row["token0_address"],
            "symbol": row["token0_symbol"],
            "decimals": row["token0_decimals"],
            "amount": decimal_to_str(amount0),
            "price_usd": format_price(price0) if price0 is not None else None,
            "value_usd": format_usd(amount0 * price0) if price0 is not None else None,
        },
        "token1": {
            "address": row["token1_address"],
            "symbol": row["token1_symbol"],
            "decimals": row["token1_decimals"],
            "amount": decimal_to_str(amount1),
            "price_usd": format_price(price1) if price1 is not None else None,
            "value_usd": format_usd(amount1 * price1) if price1 is not None else None,
        },
        "value_usd": format_usd(value),
        "updated_at": row["updated_at"],
    }


def _position_sort_key(position: dict[str, Any]) -> tuple:
    value = Decimal(position["value_usd"]) if position["value_usd"] is not None else Decimal(0)
    token_id = position["token_id"]
    return (
        position["value_usd"] is not None,
        value,
        int(token_id) if str(token_id).isdigit() else 0,
    )


def serialize_address(db: Database, row, limit: int | None = 3) -> dict[str, Any]:
    chain = row["chain"]
    definition = CHAIN_DEFINITIONS.get(chain)
    try:
        tags = json.loads(row["tags"])
        if not isinstance(tags, list):
            tags = []
    except (TypeError, json.JSONDecodeError):
        tags = []
    balance_rows = balances_for_address(db, row["id"])
    all_tokens = [_balance_dict(item) for item in balance_rows]
    for token in all_tokens:
        token["_balance_decimal"] = amount_from_raw(token["raw_balance"], token["decimals"])
        token["_value_decimal"] = Decimal(token["value_usd"]) if token["value_usd"] is not None else None

    positions = [_nft_position_dict(item) for item in positions_for_address(db, row["id"])]
    positions.sort(key=_position_sort_key, reverse=True)
    unpriced_positions = [
        position for position in positions if position["value_usd"] is None
    ]

    positive = [token for token in all_tokens if token["_balance_decimal"] > 0]
    if positive:
        shown = positive
    else:
        native = next((token for token in all_tokens if token["is_native"]), None)
        shown = [native] if native else []
    shown.sort(
        key=lambda token: (
            token["_value_decimal"] is not None,
            token["_value_decimal"] or Decimal(0),
            token["_balance_decimal"],
        ),
        reverse=True,
    )
    for token in all_tokens:
        token.pop("_balance_decimal", None)
        token.pop("_value_decimal", None)
    display_tokens = shown[:limit] if limit is not None else shown
    hidden = max(0, len(shown) - len(display_tokens)) if limit is not None else 0

    total = sum(
        (Decimal(token["value_usd"]) for token in all_tokens if token["value_usd"] is not None),
        Decimal(0),
    ) + sum(
        (
            Decimal(position["value_usd"])
            for position in positions
            if position["value_usd"] is not None
        ),
        Decimal(0),
    )
    unpriced = [
        token
        for token in all_tokens
        if token["price_usd"] is None and Decimal(token["balance"]) > 0
    ]
    if row["last_refreshed_at"] is None:
        total_status = "stale"
    elif unpriced or unpriced_positions:
        total_status = "partial"
    else:
        total_status = "complete"

    job = active_job_for_address(db, row["id"])
    return {
        "id": row["id"],
        "chain": chain,
        "chain_name": definition.name if definition else chain,
        "accent": definition.accent if definition else "#888888",
        "address": row["address"],
        "tags": tags,
        "created_at": row["created_at"],
        "last_refreshed_at": row["last_refreshed_at"],
        "last_refresh_error": row["last_refresh_error"],
        "last_refresh_warning": row["last_refresh_warning"],
        "last_refresh_provider": row["last_refresh_provider"],
        "total_usd": format_usd(total),
        "total_status": total_status,
        "unpriced_token_count": len(unpriced),
        "unpriced_position_count": len(unpriced_positions),
        "tracked_token_count": len(all_tokens),
        "hidden_token_count": hidden,
        "position_count": len(positions),
        "tokens": display_tokens,
        "positions": positions,
        "refresh": (
            {
                "job_id": job["id"],
                "status": job["status"],
                "created_at": job["created_at"],
                "started_at": job["started_at"],
            }
            if job
            else None
        ),
    }


def serialize_addresses(db: Database, rows: list) -> list[dict[str, Any]]:
    return [serialize_address(db, row, limit=3) for row in rows]


def token_registry(db: Database) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT t.id, t.symbol, t.name, t.coingecko_id, t.created_at,
               tn.id AS network_id, tn.chain, tn.contract_address, tn.decimals,
               tn.is_native, tn.enabled,
               p.price_usd, p.source AS price_source, p.fetched_at AS price_fetched_at
        FROM tokens t
        LEFT JOIN token_networks tn ON tn.token_id = t.id
        LEFT JOIN prices p ON p.token_id = t.id
        ORDER BY t.symbol COLLATE NOCASE, tn.is_native DESC, tn.chain
        """
    )
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        token = grouped.setdefault(
            row["id"],
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "name": row["name"],
                "coingecko_id": row["coingecko_id"],
                "created_at": row["created_at"],
                "price_usd": format_price(Decimal(row["price_usd"])) if row["price_usd"] else None,
                "price_source": row["price_source"],
                "price_updated_at": row["price_fetched_at"],
                "networks": [],
            },
        )
        if row["network_id"] is not None:
            token["networks"].append(
                {
                    "id": row["network_id"],
                    "chain": row["chain"],
                    "contract_address": row["contract_address"],
                    "decimals": row["decimals"],
                    "is_native": bool(row["is_native"]),
                    "enabled": bool(row["enabled"]),
                }
            )
    return list(grouped.values())


def refresh_jobs(db: Database, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.fetchall(
        """
        SELECT j.id, j.address_id, j.status, j.trigger, j.provider, j.warning, j.error,
               j.created_at, j.started_at, j.finished_at, j.duration_ms,
               a.chain, a.address
        FROM refresh_jobs j
        LEFT JOIN addresses a ON a.id = j.address_id
        ORDER BY j.id DESC LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in rows]
