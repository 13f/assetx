from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import addresses, meta, refresh, tokens
from app.chains.base import ChainAdapter
from app.chains.registry import build_adapters
from app.config import Settings
from app.db import Database
from app.seed import seed_database
from app.services.prices import PriceService
from app.services.queue import RefreshQueue
from app.services.refresh import RefreshService
from app.utils.tags import TagValidationError
from app.utils.validation import AddressValidationError

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    adapters: dict[str, ChainAdapter] | None = None,
    http_client: httpx.AsyncClient | None = None,
    price_service: PriceService | None = None,
    start_worker: bool | None = None,
) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_path)
        db.initialize()
        seed_database(db)
        owned_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds, connect=10.0),
            headers={"User-Agent": "AssetX/1.0"},
            follow_redirects=True,
        )
        active_adapters = adapters or build_adapters(settings, client)
        active_price_service = price_service or PriceService(
            db, client, cache_seconds=settings.price_cache_seconds
        )
        refresh_service = RefreshService(db, active_adapters, active_price_service)
        queue = RefreshQueue(
            db,
            refresh_service,
            interval_seconds=settings.refresh_interval_seconds,
        )
        app.state.settings = settings
        app.state.db = db
        app.state.http_client = client
        app.state.adapters = active_adapters
        app.state.price_service = active_price_service
        app.state.refresh_service = refresh_service
        app.state.queue = queue
        if (start_worker if start_worker is not None else settings.start_worker):
            await queue.start()
        try:
            yield
        finally:
            await queue.stop()
            if owned_client:
                await client.aclose()
            db.close()

    app = FastAPI(
        title="AssetX API",
        version="1.0.0",
        description="Multi-chain address portfolio tracker",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.cors_origins_list == ["*"]:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(AddressValidationError)
    async def address_validation_handler(request, exc: AddressValidationError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(TagValidationError)
    async def tag_validation_handler(request, exc: TagValidationError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    app.include_router(meta.router, prefix="/api")
    app.include_router(addresses.router, prefix="/api")
    app.include_router(tokens.router, prefix="/api")
    app.include_router(refresh.router, prefix="/api")

    @app.get("/api", include_in_schema=False)
    def api_root() -> dict:
        return {
            "name": "AssetX",
            "docs": "/api/docs",
            "health": "/api/health",
        }

    dist = settings.frontend_dist
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

        @app.exception_handler(404)
        async def not_found(request, exc):
            # API 404s stay JSON; unknown browser routes fall back to the SPA.
            if request.url.path.startswith("/api"):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            return JSONResponse(status_code=404, content={"detail": "Not found"})

    else:

        @app.get("/", include_in_schema=False)
        def root() -> dict:
            return {
                "name": "AssetX API",
                "message": "Frontend build not found. Run `bun run build` in frontend/ or use the Vite dev server.",
                "docs": "/api/docs",
            }

    return app


app = create_app()
