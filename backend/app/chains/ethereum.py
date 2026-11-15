from __future__ import annotations

from typing import Any

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

ERC20_BALANCE_OF = "0x70a08231"


class EthereumAdapter(ChainAdapter):
    chain = "ethereum"

    def _batch(self, address: str, networks: list[TokenNetwork]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = [
            {
                "jsonrpc": "2.0",
                "id": "native",
                "method": "eth_getBalance",
                "params": [address, "latest"],
            }
        ]
        body = address[2:].lower()
        if len(body) != 40:
            raise ProviderError("invalid Ethereum address")
        for network in networks:
            if network.is_native:
                continue
            if not network.contract_address:
                raise ProviderError(f"{network.symbol} is missing an ERC-20 contract address")
            calls.append(
                {
                    "jsonrpc": "2.0",
                    "id": f"token:{network.id}",
                    "method": "eth_call",
                    "params": [
                        {
                            "to": network.contract_address,
                            "data": f"{ERC20_BALANCE_OF}{'0' * 24}{body}",
                        },
                        "latest",
                    ],
                }
            )
        return calls

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        errors: list[str] = []
        calls = self._batch(address, networks)
        for url in self.providers:
            try:
                response = await self.client.post(url, json=calls)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("error"):
                    raise ProviderError(str(payload["error"]))
                if not isinstance(payload, list):
                    raise ProviderError("provider did not return a JSON-RPC batch response")
                by_id = {str(item.get("id")): item for item in payload if isinstance(item, dict)}
                native = by_id.get("native")
                if not native or "result" not in native or native.get("error"):
                    raise ProviderError(str((native or {}).get("error", "missing native balance")))
                try:
                    native_raw = int(native["result"], 16)
                except (TypeError, ValueError) as exc:
                    raise ProviderError("invalid native balance response") from exc

                balances: dict[int, str] = {}
                warnings: list[str] = []
                native_network = next((network for network in networks if network.is_native), None)
                if native_network is None:
                    raise ProviderError("native ETH token is not configured")
                balances[native_network.id] = str(native_raw)

                for network in networks:
                    if network.is_native:
                        continue
                    item = by_id.get(f"token:{network.id}")
                    if not item or item.get("error") or not item.get("result") or item["result"] == "0x":
                        reason = "empty result" if item and item.get("result") == "0x" else str(
                            (item or {}).get("error", "missing result")
                        )
                        warnings.append(f"{network.symbol}: {reason[:120]}")
                        balances[network.id] = "0"
                        continue
                    try:
                        balances[network.id] = str(int(item["result"], 16))
                    except (TypeError, ValueError):
                        warnings.append(f"{network.symbol}: invalid balance response")
                        balances[network.id] = "0"
                return FetchResult(balances=balances, provider=provider_label(url), warnings=warnings)
            except Exception as exc:  # noqa: BLE001 - fallback only on provider failure
                errors.append(f"{provider_label(url)}: {short_error(exc)}")
        raise AllProvidersFailed(self.chain, errors)
