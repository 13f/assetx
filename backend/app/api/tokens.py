from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_db, get_price_service
from app.chains.registry import get_chain
from app.db import Database
from app.schemas import TokenCreate, TokenNetworkUpsert, TokenUpdate
from app.services.prices import PriceService
from app.services.repository import token_registry
from app.utils.amounts import decimal_to_str, format_price
from app.utils.time import utcnow_iso
from app.utils.validation import AddressValidationError, validate_contract_identifier

router = APIRouter(prefix="/tokens", tags=["tokens"])


def _token_row(db: Database, token_id: int):
    row = db.fetchone("SELECT * FROM tokens WHERE id = ?", (token_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="token not found")
    return row


def _token_detail(db: Database, token_id: int) -> dict:
    return next(item for item in token_registry(db) if item["id"] == token_id)


@router.post("/prices/refresh")
async def refresh_prices(
    db: Database = Depends(get_db),
    price_service: PriceService = Depends(get_price_service),
) -> dict:
    rows = db.fetchall(
        "SELECT id, symbol FROM tokens WHERE coingecko_id IS NOT NULL ORDER BY symbol COLLATE NOCASE"
    )
    token_ids = [row["id"] for row in rows]
    symbols = {row["id"]: row["symbol"] for row in rows}
    result = await price_service.get_prices(token_ids, force=True)
    fetched_at = result.fetched_at or utcnow_iso()
    if result.prices:
        with db.transaction() as conn:
            for token_id, price in result.prices.items():
                conn.execute(
                    """
                    INSERT INTO prices(token_id, price_usd, source, fetched_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(token_id) DO UPDATE SET
                        price_usd = excluded.price_usd,
                        source = excluded.source,
                        fetched_at = excluded.fetched_at
                    """,
                    (token_id, decimal_to_str(price), result.source or "unknown", fetched_at),
                )
    return {
        "updated": len(result.prices),
        "source": result.source,
        "fetched_at": fetched_at,
        "warning": result.warning,
        "prices": {
            symbols[token_id]: format_price(price)
            for token_id, price in sorted(result.prices.items(), key=lambda item: symbols[item[0]])
        },
    }


@router.get("")
def list_tokens(db: Database = Depends(get_db)) -> dict:
    return {"items": token_registry(db)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_token(payload: TokenCreate, db: Database = Depends(get_db)) -> dict:
    symbol = payload.symbol.strip().upper()
    name = payload.name.strip()
    coingecko_id = (payload.coingecko_id or "").strip() or None
    timestamp = utcnow_iso()
    try:
        with db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO tokens(symbol, name, coingecko_id, created_at) VALUES (?, ?, ?, ?)",
                (symbol, name, coingecko_id, timestamp),
            )
            token_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Token {symbol} already exists") from exc
    return _token_detail(db, token_id)


@router.patch("/{token_id}")
def update_token(token_id: int, payload: TokenUpdate, db: Database = Depends(get_db)) -> dict:
    _token_row(db, token_id)
    fields = payload.model_fields_set
    updates: list[str] = []
    params: list[object] = []
    if "name" in fields and payload.name:
        updates.append("name = ?")
        params.append(payload.name.strip())
    if "coingecko_id" in fields:
        updates.append("coingecko_id = ?")
        params.append((payload.coingecko_id or "").strip() or None)
    if updates:
        params.append(token_id)
        with db.transaction() as conn:
            conn.execute(f"UPDATE tokens SET {', '.join(updates)} WHERE id = ?", tuple(params))
    return _token_detail(db, token_id)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_token(token_id: int, db: Database = Depends(get_db)) -> Response:
    _token_row(db, token_id)
    native = db.fetchone(
        "SELECT id FROM token_networks WHERE token_id = ? AND is_native = 1 LIMIT 1",
        (token_id,),
    )
    if native:
        raise HTTPException(status_code=409, detail="Native chain tokens cannot be deleted")
    with db.transaction() as conn:
        conn.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{token_id}/networks/{chain}")
def upsert_token_network(
    token_id: int,
    chain: str,
    payload: TokenNetworkUpsert,
    db: Database = Depends(get_db),
) -> dict:
    _token_row(db, token_id)
    definition = get_chain(chain)
    if definition is None:
        raise HTTPException(status_code=400, detail=f"unknown chain: {chain}")
    if not definition.supports_tokens:
        raise HTTPException(
            status_code=400,
            detail=f"{definition.name} does not support generic token contracts in AssetX",
        )
    existing = db.fetchone(
        "SELECT * FROM token_networks WHERE token_id = ? AND chain = ?",
        (token_id, chain),
    )
    if existing and existing["is_native"]:
        raise HTTPException(status_code=409, detail="The native token network cannot be modified")
    contract = (payload.contract_address or "").strip()
    if not contract:
        raise HTTPException(status_code=422, detail="A contract address or denom is required")
    try:
        contract = validate_contract_identifier(chain, contract)
    except AddressValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    timestamp = utcnow_iso()
    with db.transaction() as conn:
        if existing:
            conn.execute(
                """
                UPDATE token_networks
                SET contract_address = ?, decimals = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (contract, payload.decimals, 1 if payload.enabled else 0, timestamp, existing["id"]),
            )
            if existing["contract_address"] != contract:
                # Balances under an old contract are no longer meaningful.
                conn.execute("DELETE FROM balances WHERE token_network_id = ?", (existing["id"],))
        else:
            conn.execute(
                """
                INSERT INTO token_networks
                    (token_id, chain, contract_address, decimals, is_native, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    token_id,
                    chain,
                    contract,
                    payload.decimals,
                    1 if payload.enabled else 0,
                    timestamp,
                    timestamp,
                ),
            )
    return _token_detail(db, token_id)


@router.delete("/{token_id}/networks/{chain}", status_code=status.HTTP_204_NO_CONTENT)
def delete_token_network(token_id: int, chain: str, db: Database = Depends(get_db)) -> Response:
    _token_row(db, token_id)
    row = db.fetchone(
        "SELECT * FROM token_networks WHERE token_id = ? AND chain = ?",
        (token_id, chain),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="token network not found")
    if row["is_native"]:
        raise HTTPException(status_code=409, detail="The native token network cannot be deleted")
    with db.transaction() as conn:
        conn.execute("DELETE FROM token_networks WHERE id = ?", (row["id"],))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
