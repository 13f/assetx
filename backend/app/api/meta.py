from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_db, get_settings
from app.chains.registry import CHAIN_ORDER, chain_meta, get_chain
from app.config import Settings
from app.db import Database
from app.utils.time import utcnow_iso

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(db: Database = Depends(get_db)) -> dict:
    db.fetchone("SELECT 1 AS ok")
    return {"status": "ok", "time": utcnow_iso()}


@router.get("/chains")
def chains(settings: Settings = Depends(get_settings)) -> dict:
    return {"items": [chain_meta(chain, settings) for chain in CHAIN_ORDER]}


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "chains": [chain_meta(chain, settings) for chain in CHAIN_ORDER],
        "refresh_interval_seconds": settings.refresh_interval_seconds,
        "supported_tokens": [
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
        ],
    }


@router.get("/chains/{chain}")
def chain_detail(chain: str, settings: Settings = Depends(get_settings)) -> JSONResponse:
    definition = get_chain(chain)
    if definition is None:
        return JSONResponse(status_code=404, content={"detail": f"unknown chain: {chain}"})
    return JSONResponse(content=chain_meta(chain, settings))
