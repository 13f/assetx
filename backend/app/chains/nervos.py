from __future__ import annotations

from app.chains.base import (
    AllProvidersFailed,
    ChainAdapter,
    FetchResult,
    ProviderError,
    TokenNetwork,
    provider_label,
    short_error,
)
from app.utils.ckb import CkbAddressError, decode_ckb_lock


class NervosAdapter(ChainAdapter):
    chain = "nervos"

    async def fetch_balances(self, address: str, networks: list[TokenNetwork]) -> FetchResult:
        errors: list[str] = []
        native = next((network for network in networks if network.is_native), None)
        if native is None:
            raise ProviderError("native CKB token is not configured")
        try:
            lock = decode_ckb_lock(address)
        except CkbAddressError as exc:
            raise ProviderError(f"invalid CKB address: {exc}") from exc
        warnings = [
            f"{network.symbol}: Nervos user-defined token balances are not supported; only native CKB is tracked"
            for network in networks
            if not network.is_native
        ]
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "get_cells_capacity",
            "params": [{"script": lock.as_rpc(), "script_type": "lock"}],
        }
        for url in self.providers:
            try:
                response = await self.client.post(url, json=call)
                response.raise_for_status()
                data = response.json()
                if data.get("error"):
                    raise ProviderError(str(data["error"]))
                result = data.get("result")
                if result is None:
                    capacity = 0
                else:
                    capacity = int(result.get("capacity", "0x0"), 16)
                return FetchResult(balances={native.id: str(capacity)}, provider=provider_label(url), warnings=warnings)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider_label(url)}: {short_error(exc)}")
        raise AllProvidersFailed(self.chain, errors)
