from __future__ import annotations

import httpx

from app.chains.base import (
    AllProvidersFailed,
    ChainAdapter,
    FetchResult,
    ProviderError,
    TokenNetwork,
    provider_label,
    short_error,
)


class BitcoinAdapter(ChainAdapter):
    chain = "bitcoin"

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        errors: list[str] = []
        native = next((network for network in networks if network.is_native), None)
        if native is None:
            raise ProviderError("native BTC token is not configured")
        warnings = [
            f"{network.symbol}: Bitcoin token contracts are not supported; only native BTC is tracked"
            for network in networks
            if not network.is_native
        ]
        for base in self.providers:
            url = f"{base.rstrip('/')}/address/{address}"
            try:
                response = await self.client.get(url)
                if response.status_code == 404:
                    return FetchResult(balances={native.id: "0"}, provider=provider_label(base), warnings=warnings)
                response.raise_for_status()
                data = response.json()
                chain_stats = data.get("chain_stats") or {}
                mempool_stats = data.get("mempool_stats") or {}
                confirmed = int(chain_stats.get("funded_txo_sum", 0)) - int(
                    chain_stats.get("spent_txo_sum", 0)
                )
                pending = int(mempool_stats.get("funded_txo_sum", 0)) - int(
                    mempool_stats.get("spent_txo_sum", 0)
                )
                total = max(0, confirmed + pending)
                return FetchResult(balances={native.id: str(total)}, provider=provider_label(base), warnings=warnings)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider_label(base)}: {short_error(exc)}")
        raise AllProvidersFailed(self.chain, errors)
