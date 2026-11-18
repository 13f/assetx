"""Minimal Blockscout REST client for ERC-721 ownership discovery.

Uniswap V4's position manager is not ERC-721 Enumerable, so token ids cannot be
enumerated with a contract call. Blockscout's public API indexes NFT ownership
and returns the ids owned by an address; the position itself is then read
on-chain. The endpoint is keyless, which keeps AssetX usable out of the box,
and can be overridden for a self-hosted instance.
"""

from __future__ import annotations

import httpx

from app.chains.base import ProviderError, short_error

DEFAULT_BLOCKSCOUT_APIS: tuple[str, ...] = ("https://eth.blockscout.com",)


class BlockscoutClient:
    def __init__(self, client: httpx.AsyncClient, apis: list[str] | tuple[str, ...] | None = None):
        self.client = client
        self.apis = tuple(
            api.rstrip("/") for api in (apis or ()) if str(api).strip()
        ) or DEFAULT_BLOCKSCOUT_APIS

    async def erc721_token_ids(
        self,
        address: str,
        contract: str,
        limit: int = 50,
        max_pages: int = 4,
    ) -> list[str]:
        """Return up to ``limit`` token ids of ``contract`` owned by ``address``."""
        errors: list[str] = []
        for base in self.apis:
            try:
                return await self._token_ids(base, address, contract, limit, max_pages)
            except Exception as exc:  # noqa: BLE001 - endpoint fallback
                errors.append(f"{_host(base)}: {short_error(exc, 90)}")
        raise ProviderError("Blockscout NFT lookup failed: " + "; ".join(errors[:2]))

    async def _token_ids(
        self,
        base: str,
        address: str,
        contract: str,
        limit: int,
        max_pages: int,
    ) -> list[str]:
        wanted = contract.lower()
        token_ids: list[str] = []
        params: dict[str, object] = {"type": "ERC-721"}
        for _page in range(max(1, max_pages)):
            response = await self.client.get(
                f"{base}/api/v2/addresses/{address}/nft",
                params=params,
                timeout=10.0,
            )
            if response.status_code == 429:
                raise ProviderError("rate limited (429)")
            if response.status_code == 404:
                # Blockscout returns 404 for an address it has never indexed.
                return []
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError("invalid Blockscout NFT response")
            items = payload.get("items")
            if items is None:
                items = []
            if not isinstance(items, list):
                raise ProviderError("Blockscout NFT response has no items list")
            for item in items:
                if not isinstance(item, dict):
                    continue
                token = item.get("token")
                token_contract = ""
                if isinstance(token, dict):
                    token_contract = str(
                        token.get("address_hash") or token.get("address") or ""
                    ).lower()
                if token_contract != wanted:
                    continue
                token_id = str(item.get("id") or "")
                if token_id.isdigit() and token_id not in token_ids:
                    token_ids.append(token_id)
                    if len(token_ids) >= limit:
                        return token_ids
            next_page = payload.get("next_page_params")
            if not isinstance(next_page, dict) or not next_page or not items:
                break
            params = {"type": "ERC-721"}
            params.update(
                {key: value for key, value in next_page.items() if value is not None}
            )
        return token_ids


def _host(url: str) -> str:
    parsed = httpx.URL(url)
    return parsed.host or url
