from __future__ import annotations

from pydantic import BaseModel, Field


class AddressCreate(BaseModel):
    chain: str = Field(min_length=2, max_length=32)
    address: str = Field(min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list)


class AddressTagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)


class TokenCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=80)
    coingecko_id: str | None = Field(default=None, max_length=120)


class TokenUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    coingecko_id: str | None = Field(default=None, max_length=120)


class TokenNetworkUpsert(BaseModel):
    contract_address: str | None = Field(default=None, max_length=200)
    decimals: int = Field(ge=0, le=36)
    enabled: bool = True


class RefreshRequest(BaseModel):
    address_id: int | None = None
