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


def _asset_matches(key: str, identifier: str) -> bool:
    """Compare SIP-010 asset ids, ignoring only the principal address case."""
    try:
        key_contract, key_asset = key.split("::", 1)
        wanted_contract, wanted_asset = identifier.split("::", 1)
        key_principal, key_name = key_contract.split(".", 1)
        wanted_principal, wanted_name = wanted_contract.split(".", 1)
    except ValueError:
        return False
    return (
        key_principal.upper() == wanted_principal.upper()
        and key_name == wanted_name
        and key_asset == wanted_asset
    )


class StacksAdapter(ChainAdapter):
    """Reads STX and SIP-010 balances from the Hiro Stacks API.

    ``GET /extended/v1/address/{principal}/balances`` returns the native balance
    and every fungible token the principal holds, keyed by the SIP-010 asset id
    (``<contract-principal>::<asset-name>``). One request therefore covers the
    native asset and all configured tokens.
    """

    chain = "stacks"

    async def _balances(self, base: str, address: str) -> dict[str, Any]:
        response = await self.client.get(
            f"{base.rstrip('/')}/extended/v1/address/{address}/balances"
        )
        if response.status_code == 404:
            # An address without on-chain history is a valid zero balance.
            return {"stx": {"balance": "0"}, "fungible_tokens": {}}
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("invalid Stacks balances response")
        if "stx" not in payload and "fungible_tokens" not in payload:
            raise ProviderError("Stacks balances response is missing balance data")
        return payload

    @staticmethod
    def _fungible_balance(tokens: Any, identifier: str) -> int:
        if not isinstance(tokens, dict):
            raise ProviderError("invalid Stacks fungible token response")
        entry: Any = tokens.get(identifier)
        if entry is None:
            # The indexer normalizes the principal to uppercase, so compare
            # asset ids structurally instead of relying on exact string case.
            entry = next(
                (value for key, value in tokens.items() if _asset_matches(key, identifier)),
                None,
            )
        if entry is None:
            return 0
        if not isinstance(entry, dict):
            raise ProviderError(f"invalid Stacks SIP-010 balance for {identifier}")
        try:
            return int(entry.get("balance", 0))
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"invalid Stacks SIP-010 balance for {identifier}") from exc

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        errors: list[str] = []
        native = next((network for network in networks if network.is_native), None)
        if native is None:
            raise ProviderError("native STX token is not configured")

        for base in self.providers:
            try:
                payload = await self._balances(base, address)
                stx = payload.get("stx")
                if not isinstance(stx, dict):
                    raise ProviderError("Stacks balances response has no stx object")
                try:
                    native_balance = int(stx.get("balance", 0))
                except (TypeError, ValueError) as exc:
                    raise ProviderError("invalid STX balance") from exc

                fungible = payload.get("fungible_tokens") or {}
                balances: dict[int, str] = {native.id: str(native_balance)}
                warnings: list[str] = []
                for network in networks:
                    if network.is_native:
                        continue
                    identifier = network.contract_address
                    if not identifier:
                        warnings.append(f"{network.symbol}: missing SIP-010 asset identifier")
                        balances[network.id] = "0"
                        continue
                    balances[network.id] = str(self._fungible_balance(fungible, identifier))
                return FetchResult(
                    balances=balances,
                    provider=provider_label(base),
                    warnings=warnings,
                )
            except Exception as exc:  # noqa: BLE001 - provider fallback
                errors.append(f"{provider_label(base)}: {short_error(exc)}")
        raise AllProvidersFailed(self.chain, errors)
