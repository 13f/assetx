from __future__ import annotations

import asyncio
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


class SolanaAdapter(ChainAdapter):
    chain = "solana"

    async def _rpc(self, url: str, method: str, params: list[Any]) -> Any:
        response = await self.client.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        if response.status_code == 429:
            raise ProviderError("rate limited (429)")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise ProviderError(str(payload["error"])[:180])
        if not isinstance(payload, dict) or "result" not in payload:
            raise ProviderError("missing JSON-RPC result")
        return payload["result"]

    @staticmethod
    def _sum_token_accounts(result: Any) -> int:
        if not isinstance(result, dict):
            raise ProviderError("missing token account result")
        total = 0
        for account in result.get("value", []):
            try:
                info = account["account"]["data"]["parsed"]["info"]
                total += int(info["tokenAmount"]["amount"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderError("unparsable token account") from exc
        return total

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        errors: list[str] = []
        native = next((network for network in networks if network.is_native), None)
        if native is None:
            raise ProviderError("native SOL token is not configured")
        partial: FetchResult | None = None

        for url in self.providers:
            try:
                native_result = await self._rpc(
                    url,
                    "getBalance",
                    [address, {"commitment": "confirmed"}],
                )
                if not isinstance(native_result, dict):
                    raise ProviderError("invalid native balance result")
                balances: dict[int, str] = {native.id: str(int(native_result.get("value", 0)))}
                warnings: list[str] = []
                complete = True
                for network in networks:
                    if network.is_native:
                        continue
                    if not network.contract_address:
                        warnings.append(f"{network.symbol}: missing SPL mint address")
                        balances[network.id] = "0"
                        complete = False
                        continue
                    try:
                        token_result = await self._rpc(
                            url,
                            "getTokenAccountsByOwner",
                            [
                                address,
                                {"mint": network.contract_address},
                                {"encoding": "jsonParsed", "commitment": "confirmed"},
                            ],
                        )
                        balances[network.id] = str(self._sum_token_accounts(token_result))
                    except Exception:  # noqa: BLE001 - a single token can fail
                        # The official endpoint sometimes rate-limits one request.
                        await asyncio.sleep(0.25)
                        try:
                            token_result = await self._rpc(
                                url,
                                "getTokenAccountsByOwner",
                                [
                                    address,
                                    {"mint": network.contract_address},
                                    {"encoding": "jsonParsed", "commitment": "confirmed"},
                                ],
                            )
                            balances[network.id] = str(self._sum_token_accounts(token_result))
                        except Exception as retry_exc:  # noqa: BLE001
                            warnings.append(f"{network.symbol}: {short_error(retry_exc, 100)}")
                            balances[network.id] = "0"
                            complete = False
                result = FetchResult(
                    balances=balances,
                    provider=provider_label(url),
                    warnings=warnings,
                )
                if complete:
                    return result
                if partial is None:
                    partial = result
            except Exception as exc:  # noqa: BLE001 - provider fallback
                errors.append(f"{provider_label(url)}: {short_error(exc)}")

        if partial is not None:
            return partial
        raise AllProvidersFailed(self.chain, errors)
