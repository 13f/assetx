from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, get_queue
from app.db import Database
from app.services.queue import RefreshQueue
from app.services.repository import refresh_jobs

router = APIRouter(prefix="/refresh", tags=["refresh"])


@router.get("/status")
def status(queue: RefreshQueue = Depends(get_queue)) -> dict:
    return queue.status()


@router.get("/jobs")
def jobs(
    limit: int = Query(default=20, ge=1, le=100),
    db: Database = Depends(get_db),
) -> dict:
    return {"items": refresh_jobs(db, limit=limit)}
