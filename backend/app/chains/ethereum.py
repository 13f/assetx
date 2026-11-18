from __future__ import annotations

import time
from typing import Any

import httpx

from app.chains.base import (
    AllProvidersFailed,
    ChainAdapter,
    FetchResult,
    LpPosition,
    ProviderError,
    TokenNetwork,
    provider_label,
    short_error,
)
from app.chains.blockscout import BlockscoutClient
from app.chains.uniswap import (
    NftCollection,
    RpcTransport,
    UNISWAP_V4_POSITION_MANAGER,
    UniswapV3Cache,
    UniswapV3Reader,
    UniswapV4Cache,
    UniswapV4Reader,
)

ERC20_BALANCE_OF = "0x70a08231"


class EthereumAdapter(ChainAdapter):
    chain = "ethereum"

    def __init__(
        self,
        providers: list[str],
        client: httpx.AsyncClient,
        *,
        lp_collections: tuple[NftCollection, ...] | list[NftCollection] | None = None,
        lp_max_positions: int = 30,
        lp_v4_enabled: bool = False,
        lp_v4_blockscout_apis: list[str] | tuple[str, ...] | None = None,
    ):
        super().__init__(providers, client)
        # Empty by default so a bare adapter never spends RPC calls on NFT
        # discovery. The registry wires the configured collections in.
        self.lp_collections = tuple(lp_collections or ())
        self.lp_max_positions = lp_max_positions
        self.lp_v4_enabled = lp_v4_enabled
        self._lp_cache = UniswapV3Cache()
        self._v4_cache = UniswapV4Cache()
        self._blockscout = (
            BlockscoutClient(client, lp_v4_blockscout_apis)
            if lp_v4_enabled
            else None
        )
        # Avoids retrying a failing indexer on every Ethereum refresh.
        self._v4_discovery_retry_at = 0.0

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

    async def _fetch_v3_positions(
        self, address: str, limit: int
    ) -> tuple[list[LpPosition], bool, list[str]]:
        errors: list[str] = []
        for url in self.providers:
            reader = UniswapV3Reader(
                RpcTransport(self.client, url),
                cache=self._lp_cache,
                max_positions=limit,
            )
            try:
                positions, warnings, complete = await reader.read(
                    address, self.lp_collections
                )
                return positions, complete, warnings
            except Exception as exc:  # noqa: BLE001 - provider fallback
                errors.append(f"{provider_label(url)}: {short_error(exc, 100)}")
        detail = "; ".join(errors[:2]) if errors else "no RPC configured"
        return [], False, [f"Uniswap V3: all RPCs failed ({detail})"[:200]]

    async def _fetch_v4_positions(
        self, address: str, limit: int
    ) -> tuple[list[LpPosition], bool, list[str]]:
        if self._blockscout is None:
            return [], False, []
        if time.monotonic() < self._v4_discovery_retry_at:
            return [], False, ["Uniswap V4: discovery temporarily unavailable"]
        try:
            token_ids = await self._blockscout.erc721_token_ids(
                address, UNISWAP_V4_POSITION_MANAGER, limit=limit
            )
        except Exception as exc:  # noqa: BLE001 - discovery is best effort
            self._v4_discovery_retry_at = time.monotonic() + 300
            return [], False, [f"Uniswap V4: {short_error(exc, 140)}"]
        self._v4_discovery_retry_at = 0.0
        if not token_ids:
            # A successful indexer lookup with no ids is authoritative.
            return [], True, []
        errors: list[str] = []
        for url in self.providers:
            reader = UniswapV4Reader(
                RpcTransport(self.client, url),
                cache=self._v4_cache,
                max_positions=limit,
            )
            try:
                positions, warnings, complete = await reader.read(address, token_ids)
                return positions, complete, warnings
            except Exception as exc:  # noqa: BLE001 - provider fallback
                errors.append(f"{provider_label(url)}: {short_error(exc, 100)}")
        detail = "; ".join(errors[:2]) if errors else "no RPC configured"
        return [], False, [f"Uniswap V4: all RPCs failed ({detail})"[:200]]

    async def _fetch_positions(
        self, address: str
    ) -> tuple[list[LpPosition], set[str], list[str]]:
        """Enumerate LP NFTs, failing over between RPC endpoints.

        Position discovery is best effort: a wallet's fungible balances are
        still useful when a position manager cannot be read, so this never
        raises into the balance path. Completeness is tracked per protocol so a
        V4 indexer outage does not discard saved V3 positions.
        """
        positions: list[LpPosition] = []
        complete: set[str] = set()
        warnings: list[str] = []

        if self.lp_collections:
            v3_positions, v3_complete, v3_warnings = await self._fetch_v3_positions(
                address, self.lp_max_positions
            )
            positions.extend(v3_positions)
            warnings.extend(v3_warnings)
            if v3_complete:
                complete.add("uniswap-v3")

        if self.lp_v4_enabled and self._blockscout is not None:
            remaining = max(0, self.lp_max_positions - len(positions))
            if remaining <= 0:
                warnings.append("Uniswap V4: position limit reached")
            else:
                v4_positions, v4_complete, v4_warnings = await self._fetch_v4_positions(
                    address, remaining
                )
                positions.extend(v4_positions)
                warnings.extend(v4_warnings)
                if v4_complete:
                    complete.add("uniswap-v4")

        return positions, complete, warnings

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

                positions, positions_complete, lp_warnings = await self._fetch_positions(address)
                warnings.extend(lp_warnings)
                return FetchResult(
                    balances=balances,
                    provider=provider_label(url),
                    warnings=warnings,
                    positions=positions,
                    positions_complete=positions_complete,
                )
            except Exception as exc:  # noqa: BLE001 - fallback only on provider failure
                errors.append(f"{provider_label(url)}: {short_error(exc)}")
        raise AllProvidersFailed(self.chain, errors)
