from __future__ import annotations

from typing import Any

from app.chains.base import (
    AllProvidersFailed,
    ChainAdapter,
    FetchResult,
    ProviderError,
    TokenNetwork,
    provider_label,
    short_error,
)

NATIVE_DENOM = "uatom"


class CosmosAdapter(ChainAdapter):
    chain = "cosmos"

    async def _bank_balances(self, base: str, address: str) -> dict[str, int]:
        balances: dict[str, int] = {}
        next_key: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"pagination.limit": "1000"}
            if next_key:
                params["pagination.key"] = next_key
            response = await self.client.get(
                f"{base.rstrip('/')}/cosmos/bank/v1beta1/balances/{address}",
                params=params,
            )
            if response.status_code == 404:
                return balances
            response.raise_for_status()
            data = response.json()
            for coin in data.get("balances", []):
                try:
                    balances[coin["denom"]] = balances.get(coin["denom"], 0) + int(coin["amount"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProviderError("invalid Cosmos bank balance response") from exc
            next_key = (data.get("pagination") or {}).get("next_key")
            if not next_key:
                break
        return balances

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        errors: list[str] = []
        native = next((network for network in networks if network.is_native), None)
        if native is None:
            raise ProviderError("native ATOM token is not configured")
        for base in self.providers:
            try:
                denoms = await self._bank_balances(base, address)
                result: dict[int, str] = {}
                warnings: list[str] = []
                for network in networks:
                    denom = NATIVE_DENOM if network.is_native else network.contract_address
                    if not denom:
                        warnings.append(f"{network.symbol}: missing Cosmos denom")
                        result[network.id] = "0"
                        continue
                    result[network.id] = str(denoms.get(denom, 0))
                return FetchResult(balances=result, provider=provider_label(base), warnings=warnings)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider_label(base)}: {short_error(exc)}")
        raise AllProvidersFailed(self.chain, errors)
