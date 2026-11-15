from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import get_db, get_queue, get_settings
from app.chains.registry import get_chain
from app.config import Settings
from app.db import Database
from app.schemas import AddressCreate, AddressTagsUpdate
from app.services.queue import RefreshQueue
from app.services.repository import (
    get_address,
    list_address_rows,
    serialize_address,
    serialize_addresses,
)
from app.utils.tags import TagValidationError, normalize_tags
from app.utils.time import utcnow_iso
from app.utils.validation import AddressValidationError, normalize_address

router = APIRouter(prefix="/addresses", tags=["addresses"])


def _normalized_tags(tags: list[str], settings: Settings) -> list[str]:
    try:
        return normalize_tags(tags, max_tags=settings.max_tags_per_address)
    except TagValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_addresses(
    chain: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Database = Depends(get_db),
) -> dict:
    if chain and get_chain(chain) is None:
        raise HTTPException(status_code=400, detail=f"unknown chain: {chain}")
    rows = list_address_rows(db)
    if chain:
        rows = [row for row in rows if row["chain"] == chain]
    if tag:
        wanted = tag.strip().lower()

        def has_tag(row) -> bool:
            try:
                values = json.loads(row["tags"])
            except (TypeError, json.JSONDecodeError):
                values = []
            return wanted in [str(item).strip().lower() for item in values]

        rows = [row for row in rows if has_tag(row)]
    if q:
        needle = q.strip().lower()
        rows = [
            row
            for row in rows
            if needle in row["address"].lower() or needle in (row["tags"] or "").lower()
        ]
    items = serialize_addresses(db, rows)
    return {"items": items, "total": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_address(
    payload: AddressCreate,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if get_chain(payload.chain) is None:
        raise HTTPException(status_code=400, detail=f"unknown chain: {payload.chain}")
    try:
        normalized = normalize_address(payload.chain, payload.address)
    except AddressValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    tags = _normalized_tags(payload.tags, settings)
    timestamp = utcnow_iso()

    try:
        with db.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO addresses(chain, address, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (payload.chain, normalized, json.dumps(tags), timestamp, timestamp),
            )
            address_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="This address is already tracked on this chain") from exc
    row = get_address(db, address_id)
    return serialize_address(db, row, limit=None)


@router.get("/{address_id}")
def read_address(address_id: int, db: Database = Depends(get_db)) -> dict:
    row = get_address(db, address_id)
    if row is None:
        raise HTTPException(status_code=404, detail="address not found")
    return serialize_address(db, row, limit=None)


@router.patch("/{address_id}")
def update_address_tags(
    address_id: int,
    payload: AddressTagsUpdate,
    db: Database = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = get_address(db, address_id)
    if row is None:
        raise HTTPException(status_code=404, detail="address not found")
    tags = _normalized_tags(payload.tags, settings)

    with db.transaction() as conn:
        conn.execute(
            "UPDATE addresses SET tags = ?, updated_at = ? WHERE id = ?",
            (json.dumps(tags), utcnow_iso(), address_id),
        )
    return serialize_address(db, get_address(db, address_id), limit=None)


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: int, db: Database = Depends(get_db)) -> Response:
    row = get_address(db, address_id)
    if row is None:
        raise HTTPException(status_code=404, detail="address not found")
    with db.transaction() as conn:
        conn.execute("DELETE FROM addresses WHERE id = ?", (address_id,))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/refresh-all", status_code=status.HTTP_202_ACCEPTED)
async def refresh_all(
    db: Database = Depends(get_db),
    queue: RefreshQueue = Depends(get_queue),
) -> dict:
    rows = list_address_rows(db)
    jobs = await queue.enqueue_many([row["id"] for row in rows])
    return {"jobs": jobs, "count": len(jobs), "status": queue.status()}


@router.post("/{address_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_address(
    address_id: int,
    db: Database = Depends(get_db),
    queue: RefreshQueue = Depends(get_queue),
) -> dict:
    row = get_address(db, address_id)
    if row is None:
        raise HTTPException(status_code=404, detail="address not found")
    job = await queue.enqueue(address_id)
    return {"job": job, "status": queue.status()}
