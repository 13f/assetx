from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.db import Database
from app.services.prices import PriceService
from app.services.queue import RefreshQueue
from app.services.refresh import RefreshService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_queue(request: Request) -> RefreshQueue:
    return request.app.state.queue


def get_refresh_service(request: Request) -> RefreshService:
    return request.app.state.refresh_service


def get_price_service(request: Request) -> PriceService:
    return request.app.state.price_service
