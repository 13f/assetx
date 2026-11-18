"""Uniswap V3 and V4 liquidity positions (LP NFTs) on Ethereum.

A Uniswap V3 position is an ERC-721 token owned by the canonical
``NonfungiblePositionManager``. AssetX reads the token ids owned by a wallet,
the on-chain position struct, the pool's current sqrt price, and the metadata of
the two underlying ERC-20s. The concrete token amounts follow from Uniswap's
concentrated-liquidity math (whitepaper section 6.29/6.30). Everything is
computed with integer arithmetic so no floating-point drift leaks into
balances.

V4 positions live in the singleton ``PositionManager``. That contract is
ERC-721 but not Enumerable, so token ids are discovered by an indexer and the
position is then read on-chain with ``getPoolAndPositionInfo``,
``getPositionLiquidity``, and ``StateView.getSlot0``. ``poolId`` is the Keccak
hash of the ABI-encoded ``PoolKey``.

The readers are transport-agnostic: they only need a ``RpcTransport``, which
turns one round of ``eth_call`` requests into one JSON-RPC batch. That keeps the
provider-failover logic in :mod:`app.chains.ethereum`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext

import httpx

from app.chains.base import LpPosition, ProviderError, short_error
from app.utils.keccak import keccak256

Q96 = 1 << 96
TICK_MULTIPLIER = Decimal("1.0001")
MIN_TICK = -887272
MAX_TICK = 887272

# 4-byte selectors, precomputed from the ABI signatures.
SEL_BALANCE_OF = "0x70a08231"  # balanceOf(address)
SEL_TOKEN_OF_OWNER_BY_INDEX = "0x2f745c59"  # tokenOfOwnerByIndex(address,uint256)
SEL_POSITIONS = "0x99fbab88"  # positions(uint256)
SEL_FACTORY = "0xc45a0155"  # factory()
SEL_GET_POOL = "0x1698ee82"  # getPool(address,address,uint24)
SEL_SLOT0 = "0x3850c7bd"  # slot0()
SEL_SYMBOL = "0x95d89b41"  # symbol()
SEL_DECIMALS = "0x313ce567"  # decimals()

# Canonical Uniswap V3 NonfungiblePositionManager on Ethereum mainnet.
UNISWAP_V3_POSITION_MANAGER = "0xc36442b4a4522e871399cd717abdd847ab11fe88"

# Uniswap V4 singleton position manager and its read-only StateView on
# Ethereum mainnet. The position manager is ERC-721 but not Enumerable.
UNISWAP_V4_POSITION_MANAGER = "0xbd216513d74c8cf14cf4747e6aaa6420ff64ee9e"
UNISWAP_V4_STATE_VIEW = "0x7ffe42c4a5deea5b0fec41c94c136cf115597227"
NATIVE_CURRENCY = "0x0000000000000000000000000000000000000000"

SEL_GET_POOL_AND_POSITION_INFO = "0x7ba03aad"  # getPoolAndPositionInfo(uint256)
SEL_GET_POSITION_LIQUIDITY = "0x1efeed33"  # getPositionLiquidity(uint256)
SEL_V4_GET_SLOT0 = "0xc815641c"  # getSlot0(bytes32)
SEL_OWNER_OF = "0x6352211e"  # ownerOf(uint256)


@dataclass(frozen=True)
class NftCollection:
    """An ERC-721 position-manager contract that exposes Uniswap V3 positions."""

    protocol: str
    name: str
    contract_address: str
    kind: str = "liquidity"


UNISWAP_V3_COLLECTION = NftCollection(
    protocol="uniswap-v3",
    name="Uniswap V3",
    contract_address=UNISWAP_V3_POSITION_MANAGER,
)
DEFAULT_NFT_COLLECTIONS: tuple[NftCollection, ...] = (UNISWAP_V3_COLLECTION,)


@dataclass
class UniswapV3Cache:
    """Immutable-on-chain lookups shared across refreshes of one adapter.

    Factory addresses, pool addresses, and ERC-20 symbols/decimals never change,
    so caching them avoids repeating two thirds of the RPC traffic during a
    "refresh all" batch.
    """

    factory_by_collection: dict[str, str] = field(default_factory=dict)
    pool_by_key: dict[tuple[str, str, int], str] = field(default_factory=dict)
    token_meta: dict[str, tuple[str, int]] = field(default_factory=dict)


def sqrt_ratio_at_tick(tick: int) -> int:
    """Return ``floor(sqrt(1.0001**tick) * 2**96)``.

    This mirrors Uniswap's ``TickMath.getSqrtRatioAtTick`` closely enough for
    display-grade balances: 60 decimal digits keep the error far below one base
    unit for any real position.
    """
    if tick < MIN_TICK or tick > MAX_TICK:
        raise ValueError(f"tick out of range: {tick}")
    with localcontext() as ctx:
        ctx.prec = 60
        ratio = TICK_MULTIPLIER**tick
        sqrt = ratio.sqrt()
        return int(sqrt * Decimal(Q96))


def position_amounts(
    liquidity: int,
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
) -> tuple[int, int]:
    """Return ``(amount0_raw, amount1_raw)`` for a Uniswap V3 position.

    The formulas are the standard concentrated-liquidity relations:

    * below the range: all token0
    * above the range: all token1
    * inside the range: a mix of both

    Integer division floors every result, exactly like the pool contracts do.
    """
    if liquidity <= 0 or tick_lower >= tick_upper:
        return (0, 0)
    sqrt_lower = sqrt_ratio_at_tick(tick_lower)
    sqrt_upper = sqrt_ratio_at_tick(tick_upper)
    if sqrt_lower <= 0 or sqrt_upper <= 0 or sqrt_price_x96 <= 0:
        return (0, 0)
    if sqrt_price_x96 <= sqrt_lower:
        amount0 = (liquidity * (sqrt_upper - sqrt_lower) * Q96) // (sqrt_lower * sqrt_upper)
        return (amount0, 0)
    if sqrt_price_x96 >= sqrt_upper:
        amount1 = (liquidity * (sqrt_upper - sqrt_lower)) // Q96
        return (0, amount1)
    amount0 = (liquidity * (sqrt_upper - sqrt_price_x96) * Q96) // (
        sqrt_price_x96 * sqrt_upper
    )
    amount1 = (liquidity * (sqrt_price_x96 - sqrt_lower)) // Q96
    return (amount0, amount1)


def _strip_hex(value: str) -> str:
    text = value.strip()
    if text.startswith(("0x", "0X")):
        return text[2:]
    return text


def _abi_words(data: str) -> list[int]:
    body = _strip_hex(data)
    if len(body) % 64 != 0:
        raise ProviderError("truncated ABI response")
    return [int(body[index : index + 64], 16) for index in range(0, len(body), 64)]


def _address_from_word(word: int) -> str:
    return f"0x{word & ((1 << 160) - 1):040x}"


def _signed_from_word(word: int) -> int:
    # ABI sign-extends int24 to 32 bytes, so the two's-complement conversion
    # below recovers the original signed value.
    return word - (1 << 256) if word >= (1 << 255) else word


def _signed_from_24(value: int) -> int:
    # Packed V4 PositionInfo stores int24 values without byte padding.
    return value - (1 << 24) if value >= (1 << 23) else value


def decode_abi_string(data: str) -> str:
    """Decode a Solidity ``string`` return value, tolerating bytes32 symbols."""
    body = _strip_hex(data)
    if not body:
        return ""
    chunks = [body[index : index + 64] for index in range(0, len(body), 64)]
    try:
        offset = int(chunks[0], 16)
    except ValueError:
        return ""
    if offset == 32 and len(chunks) >= 2:
        try:
            length = int(chunks[1], 16)
        except ValueError:
            return ""
        if length <= 256 and len(chunks) * 32 >= 64 + length:
            payload = "".join(chunks[2:])[: length * 2]
            try:
                return bytes.fromhex(payload).decode("utf-8", errors="replace").strip()
            except ValueError:
                return ""
    # Legacy tokens such as MKR return a left-aligned bytes32 symbol.
    try:
        raw = bytes.fromhex(chunks[0])
    except ValueError:
        return ""
    return raw.rstrip(b"\x00").decode("utf-8", errors="replace").strip()


class RpcTransport:
    """One JSON-RPC endpoint that executes rounds of batched ``eth_call``."""

    def __init__(self, client: httpx.AsyncClient, url: str):
        self.client = client
        self.url = url

    async def call_batch(
        self,
        calls: list[tuple[str, str]],
        chunk_size: int = 16,
    ) -> list[str | None]:
        """Run ``(to, data)`` calls, returning one result (or ``None``) per call.

        ``None`` means that specific call reverted or was rejected by the node;
        transport, HTTP, and malformed-envelope failures raise ``ProviderError``
        so the caller can fail over to the next endpoint.
        """
        results: list[str | None] = []
        for start in range(0, len(calls), chunk_size):
            chunk = calls[start : start + chunk_size]
            payload = [
                {
                    "jsonrpc": "2.0",
                    "id": f"lp{index}",
                    "method": "eth_call",
                    "params": [{"to": to, "data": data}, "latest"],
                }
                for index, (to, data) in enumerate(chunk)
            ]
            try:
                response = await self.client.post(self.url, json=payload)
            except httpx.HTTPError as exc:
                raise ProviderError(short_error(exc)) from exc
            if response.status_code == 429:
                raise ProviderError("rate limited (429)")
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise ProviderError("invalid JSON-RPC response") from exc
            if isinstance(body, dict) and body.get("error"):
                raise ProviderError(str(body["error"])[:180])
            if not isinstance(body, list):
                raise ProviderError("provider did not return a JSON-RPC batch response")
            by_id = {
                str(item.get("id")): item for item in body if isinstance(item, dict)
            }
            for index in range(len(chunk)):
                item = by_id.get(f"lp{index}")
                if item is None:
                    raise ProviderError("missing JSON-RPC batch item")
                if item.get("error"):
                    results.append(None)
                    continue
                result = item.get("result")
                results.append(result if isinstance(result, str) else None)
        return results


@dataclass
class _RawPosition:
    collection: NftCollection
    token_id: int
    token0: str
    token1: str
    fee: int
    tick_lower: int
    tick_upper: int
    liquidity: int


class UniswapV3Reader:
    """Reads LP positions with as few sequential RPC rounds as possible."""

    def __init__(
        self,
        transport: RpcTransport,
        cache: UniswapV3Cache | None = None,
        max_positions: int = 30,
    ):
        self.transport = transport
        self.cache = cache or UniswapV3Cache()
        self.max_positions = max(1, min(int(max_positions), 200))

    async def read(
        self,
        owner: str,
        collections: tuple[NftCollection, ...] | list[NftCollection],
    ) -> tuple[list[LpPosition], list[str], bool]:
        """Return ``(positions, warnings, complete)``.

        ``complete`` is False when any enumerated position could not be fully
        decoded. Callers keep the previously saved position set in that case so
        a transient or malformed read never silently deletes positions.
        """
        warnings: list[str] = []
        liquidity_collections = [
            collection for collection in collections if collection.kind == "liquidity"
        ]
        if not liquidity_collections:
            return [], warnings, False
        owner_word = f"{int(owner, 16):064x}"

        counts = await self.transport.call_batch(
            [
                (collection.contract_address, SEL_BALANCE_OF + owner_word)
                for collection in liquidity_collections
            ]
        )

        references: list[tuple[NftCollection, int]] = []
        remaining = self.max_positions
        for collection, raw_count in zip(liquidity_collections, counts):
            if raw_count is None or raw_count in {"", "0x"}:
                # A failed balanceOf means the scan is not authoritative.
                raise ProviderError(f"{collection.name}: balanceOf failed")
            try:
                count = int(raw_count, 16)
            except ValueError as exc:
                raise ProviderError(
                    f"{collection.name}: invalid balanceOf response"
                ) from exc
            if remaining <= 0:
                if count > 0:
                    warnings.append(
                        f"{collection.name}: {count} positions not scanned (limit reached)"
                    )
                continue
            taken = min(count, remaining)
            remaining -= taken
            if count > taken:
                warnings.append(
                    f"{collection.name}: showing {taken} of {count} positions"
                )
            references.extend((collection, index) for index in range(taken))

        if not references:
            return [], warnings, True

        complete = True
        id_results = await self.transport.call_batch(
            [
                (
                    collection.contract_address,
                    SEL_TOKEN_OF_OWNER_BY_INDEX + owner_word + f"{index:064x}",
                )
                for collection, index in references
            ]
        )
        entries: list[tuple[NftCollection, int]] = []
        seen: set[tuple[str, int]] = set()
        for (collection, index), raw_id in zip(references, id_results):
            if raw_id is None or raw_id in {"", "0x"}:
                warnings.append(f"{collection.name}: could not enumerate position #{index}")
                complete = False
                continue
            try:
                token_id = int(raw_id, 16)
            except ValueError:
                warnings.append(f"{collection.name}: invalid token id at #{index}")
                complete = False
                continue
            key = (collection.contract_address, token_id)
            if key in seen or token_id == 0:
                continue
            seen.add(key)
            entries.append((collection, token_id))

        if not entries:
            raise ProviderError("could not enumerate any position ids")

        raw_positions: list[_RawPosition] = []
        for (collection, token_id), data in zip(
            entries,
            await self.transport.call_batch(
                [
                    (collection.contract_address, SEL_POSITIONS + f"{token_id:064x}")
                    for collection, token_id in entries
                ]
            ),
        ):
            if data is None or data in {"", "0x"}:
                warnings.append(f"{collection.name} #{token_id}: positions() failed")
                complete = False
                continue
            try:
                words = _abi_words(data)
                if len(words) < 12:
                    raise ProviderError("short positions() response")
                token0 = _address_from_word(words[2])
                token1 = _address_from_word(words[3])
                if int(token0, 16) == 0 or int(token1, 16) == 0:
                    warnings.append(f"{collection.name} #{token_id}: empty token pair")
                    complete = False
                    continue
                raw_positions.append(
                    _RawPosition(
                        collection=collection,
                        token_id=token_id,
                        token0=token0,
                        token1=token1,
                        fee=words[4],
                        tick_lower=_signed_from_word(words[5]),
                        tick_upper=_signed_from_word(words[6]),
                        liquidity=words[7],
                    )
                )
            except (ProviderError, ValueError):
                warnings.append(f"{collection.name} #{token_id}: unreadable position")
                complete = False

        if not raw_positions:
            raise ProviderError("positions() failed for every position")

        factories = await self._factories(raw_positions)
        pools = await self._pools(raw_positions, factories, warnings)
        if not pools:
            raise ProviderError("could not resolve any Uniswap V3 pool")

        used_pools = {
            pools[(position.token0, position.token1, position.fee)]
            for position in raw_positions
            if (position.token0, position.token1, position.fee) in pools
        }
        sqrt_prices = await self._slot0(used_pools)
        token_meta = await self._token_metadata(raw_positions)

        positions: list[LpPosition] = []
        for raw in raw_positions:
            key = (raw.token0, raw.token1, raw.fee)
            pool = pools.get(key)
            if not pool:
                warnings.append(
                    f"{raw.collection.name} #{raw.token_id}: pool not found"
                )
                complete = False
                continue
            sqrt_price = sqrt_prices.get(pool)
            if sqrt_price is None:
                warnings.append(f"{raw.collection.name} #{raw.token_id}: slot0() unavailable")
                complete = False
                continue
            meta0 = token_meta.get(raw.token0)
            meta1 = token_meta.get(raw.token1)
            if meta0 is None or meta1 is None:
                warnings.append(
                    f"{raw.collection.name} #{raw.token_id}: token metadata unavailable"
                )
                complete = False
                continue
            amount0, amount1 = position_amounts(
                raw.liquidity,
                sqrt_price[0],
                raw.tick_lower,
                raw.tick_upper,
            )
            positions.append(
                LpPosition(
                    protocol=raw.collection.protocol,
                    collection=raw.collection.name,
                    contract_address=raw.collection.contract_address,
                    token_id=str(raw.token_id),
                    pool_address=pool,
                    token0_address=raw.token0,
                    token0_symbol=meta0[0],
                    token0_decimals=meta0[1],
                    token0_amount_raw=str(amount0),
                    token1_address=raw.token1,
                    token1_symbol=meta1[0],
                    token1_decimals=meta1[1],
                    token1_amount_raw=str(amount1),
                    fee_tier=raw.fee,
                    tick_lower=raw.tick_lower,
                    tick_upper=raw.tick_upper,
                    liquidity=str(raw.liquidity),
                    in_range=raw.tick_lower <= sqrt_price[1] < raw.tick_upper,
                )
            )
        if len(positions) != len(raw_positions):
            complete = False
        return positions, warnings, complete

    async def _factories(self, positions: list[_RawPosition]) -> dict[str, str]:
        needed = {
            position.collection.contract_address
            for position in positions
            if position.collection.contract_address not in self.cache.factory_by_collection
        }
        if not needed:
            return self.cache.factory_by_collection
        ordered = sorted(needed)
        results = await self.transport.call_batch(
            [(contract, SEL_FACTORY) for contract in ordered]
        )
        for contract, data in zip(ordered, results):
            if data is None or data in {"", "0x"}:
                continue
            try:
                self.cache.factory_by_collection[contract] = _address_from_word(
                    _abi_words(data)[0]
                )
            except (ProviderError, ValueError, IndexError):
                continue
        return self.cache.factory_by_collection

    async def _pools(
        self,
        positions: list[_RawPosition],
        factories: dict[str, str],
        warnings: list[str],
    ) -> dict[tuple[str, str, int], str]:
        keys = {(position.token0, position.token1, position.fee) for position in positions}
        missing: dict[tuple[str, str, int], str] = {}
        warned: set[str] = set()
        for position in positions:
            key = (position.token0, position.token1, position.fee)
            if key in self.cache.pool_by_key or key in missing:
                continue
            factory = factories.get(position.collection.contract_address)
            if not factory:
                if position.collection.name not in warned:
                    warned.add(position.collection.name)
                    warnings.append(f"{position.collection.name}: factory() unavailable")
                continue
            missing[key] = factory
        if missing:
            items = list(missing.items())
            results = await self.transport.call_batch(
                [
                    (
                        factory,
                        SEL_GET_POOL
                        + f"{int(key[0], 16):064x}"
                        + f"{int(key[1], 16):064x}"
                        + f"{key[2]:064x}",
                    )
                    for key, factory in items
                ]
            )
            for (key, _factory), data in zip(items, results):
                if data is None or data in {"", "0x"}:
                    continue
                try:
                    pool = _address_from_word(_abi_words(data)[0])
                except (ProviderError, ValueError, IndexError):
                    continue
                if int(pool, 16) != 0:
                    self.cache.pool_by_key[key] = pool
        return {
            key: self.cache.pool_by_key[key]
            for key in keys
            if key in self.cache.pool_by_key
        }

    async def _slot0(self, pool_addresses: set[str]) -> dict[str, tuple[int, int]]:
        ordered = sorted(pool_addresses)
        if not ordered:
            return {}
        results = await self.transport.call_batch(
            [(pool, SEL_SLOT0) for pool in ordered]
        )
        prices: dict[str, tuple[int, int]] = {}
        for pool, data in zip(ordered, results):
            if data is None or data in {"", "0x"}:
                continue
            try:
                words = _abi_words(data)
                if len(words) < 2:
                    continue
                prices[pool] = (words[0], _signed_from_word(words[1]))
            except (ProviderError, ValueError):
                continue
        return prices

    async def _token_metadata(
        self,
        positions: list[_RawPosition],
    ) -> dict[str, tuple[str, int]]:
        addresses = sorted(
            {
                address
                for position in positions
                for address in (position.token0, position.token1)
                if address not in self.cache.token_meta
            }
        )
        if not addresses:
            return self.cache.token_meta
        calls: list[tuple[str, str]] = []
        for address in addresses:
            calls.append((address, SEL_SYMBOL))
            calls.append((address, SEL_DECIMALS))
        results = await self.transport.call_batch(calls)
        for index, address in enumerate(addresses):
            symbol_data = results[index * 2]
            decimals_data = results[index * 2 + 1]
            symbol = decode_abi_string(symbol_data) if symbol_data else ""
            symbol = symbol.strip()[:32] or address[:8]
            decimals: int | None = None
            if decimals_data and decimals_data not in {"", "0x"}:
                try:
                    candidate = _abi_words(decimals_data)[0]
                    if 0 <= candidate <= 36:
                        decimals = candidate
                except (ProviderError, ValueError, IndexError):
                    decimals = None
            # Decimals are required to convert raw base units; cache only when
            # they decoded so the next refresh can try again.
            if decimals is not None:
                self.cache.token_meta[address] = (symbol, decimals)
        return self.cache.token_meta


# ---------------------------------------------------------------------------
# Uniswap V4
# ---------------------------------------------------------------------------


@dataclass
class UniswapV4Cache:
    """Token metadata shared across refreshes of one adapter."""

    token_meta: dict[str, tuple[str, int]] = field(default_factory=dict)


def encode_pool_key(
    key: tuple[str, str, int, int, str],
) -> bytes:
    """ABI-encode a V4 ``PoolKey`` the way ``keccak256(abi.encode(poolKey))`` does."""
    currency0, currency1, fee, tick_spacing, hooks = key

    def word(value: int) -> bytes:
        return (value & ((1 << 256) - 1)).to_bytes(32, "big")

    return (
        word(int(currency0, 16))
        + word(int(currency1, 16))
        + word(fee)
        + word(tick_spacing)
        + word(int(hooks, 16))
    )


def pool_id_for_key(key: tuple[str, str, int, int, str]) -> str:
    return "0x" + keccak256(encode_pool_key(key)).hex()


def decode_pool_key_and_info(data: str) -> tuple[tuple[str, str, int, int, str], int]:
    """Decode ``getPoolAndPositionInfo`` into ``(poolKey, packedPositionInfo)``."""
    words = _abi_words(data)
    if len(words) < 6:
        raise ProviderError("short getPoolAndPositionInfo response")
    key = (
        _address_from_word(words[0]),
        _address_from_word(words[1]),
        words[2],
        _signed_from_word(words[3]),
        _address_from_word(words[4]),
    )
    return key, words[5]


class UniswapV4Reader:
    """Read V4 positions for token ids discovered by an external indexer."""

    def __init__(
        self,
        transport: RpcTransport,
        cache: UniswapV4Cache | None = None,
        max_positions: int = 30,
        native_symbol: str = "ETH",
        native_decimals: int = 18,
    ):
        self.transport = transport
        self.cache = cache or UniswapV4Cache()
        self.max_positions = max(1, min(int(max_positions), 200))
        self.native_symbol = native_symbol
        self.native_decimals = native_decimals

    async def read(
        self,
        owner: str,
        token_ids: list[str] | tuple[str, ...],
    ) -> tuple[list[LpPosition], list[str], bool]:
        unique = [
            str(token_id)
            for token_id in dict.fromkeys(token_ids)
            if str(token_id).isdigit()
        ][: self.max_positions]
        if not unique:
            return [], [], True

        calls: list[tuple[str, str]] = []
        for token_id in unique:
            word = f"{int(token_id):064x}"
            calls.append((UNISWAP_V4_POSITION_MANAGER, SEL_GET_POOL_AND_POSITION_INFO + word))
            calls.append((UNISWAP_V4_POSITION_MANAGER, SEL_GET_POSITION_LIQUIDITY + word))
            calls.append((UNISWAP_V4_POSITION_MANAGER, SEL_OWNER_OF + word))
        results = await self.transport.call_batch(calls)

        warnings: list[str] = []
        complete = True
        entries: list[
            tuple[str, tuple[str, str, int, int, str], int, int, int]
        ] = []
        owner_lower = owner.lower()
        for index, token_id in enumerate(unique):
            info_data, liquidity_data, owner_data = results[index * 3 : index * 3 + 3]
            if not info_data or not liquidity_data or not owner_data:
                warnings.append(f"Uniswap V4 #{token_id}: position read failed")
                complete = False
                continue
            try:
                key, packed = decode_pool_key_and_info(info_data)
                liquidity = _abi_words(liquidity_data)[0]
                current_owner = _address_from_word(_abi_words(owner_data)[0])
            except (ProviderError, ValueError, IndexError):
                warnings.append(f"Uniswap V4 #{token_id}: unreadable position")
                complete = False
                continue
            if current_owner != owner_lower:
                # An indexer can lag a transfer; the owner call is authoritative.
                warnings.append(f"Uniswap V4 #{token_id}: no longer owned")
                continue
            tick_lower = _signed_from_24((packed >> 8) & 0xFFFFFF)
            tick_upper = _signed_from_24((packed >> 32) & 0xFFFFFF)
            if tick_lower >= tick_upper:
                warnings.append(f"Uniswap V4 #{token_id}: invalid tick range")
                complete = False
                continue
            entries.append((token_id, key, tick_lower, tick_upper, liquidity))

        if not entries:
            if complete:
                return [], warnings, True
            raise ProviderError("could not read any Uniswap V4 position")

        pool_id_by_key: dict[tuple[str, str, int, int, str], str] = {}
        for _token_id, key, _lower, _upper, _liquidity in entries:
            pool_id_by_key.setdefault(key, pool_id_for_key(key))
        pool_ids = sorted(set(pool_id_by_key.values()))
        slot_results = await self.transport.call_batch(
            [(UNISWAP_V4_STATE_VIEW, SEL_V4_GET_SLOT0 + pool_id[2:]) for pool_id in pool_ids]
        )
        slots: dict[str, tuple[int, int, int]] = {}
        for pool_id, data in zip(pool_ids, slot_results):
            if not data:
                continue
            try:
                words = _abi_words(data)
                if len(words) < 4:
                    continue
                slots[pool_id] = (
                    words[0],
                    _signed_from_word(words[1]),
                    words[3],  # current lpFee
                )
            except (ProviderError, ValueError):
                continue

        token_meta = await self._token_metadata(entries)

        positions: list[LpPosition] = []
        for token_id, key, tick_lower, tick_upper, liquidity in entries:
            pool_id = pool_id_by_key[key]
            slot = slots.get(pool_id)
            if slot is None:
                warnings.append(f"Uniswap V4 #{token_id}: slot0() unavailable")
                complete = False
                continue
            meta0 = token_meta.get(key[0])
            meta1 = token_meta.get(key[1])
            if meta0 is None or meta1 is None:
                warnings.append(f"Uniswap V4 #{token_id}: token metadata unavailable")
                complete = False
                continue
            sqrt_price, current_tick, lp_fee = slot
            amount0, amount1 = position_amounts(
                liquidity, sqrt_price, tick_lower, tick_upper
            )
            fee_tier = lp_fee if 0 < lp_fee <= 1_000_000 else key[2]
            positions.append(
                LpPosition(
                    protocol="uniswap-v4",
                    collection="Uniswap V4",
                    contract_address=UNISWAP_V4_POSITION_MANAGER,
                    token_id=str(token_id),
                    pool_address=pool_id,
                    token0_address=key[0],
                    token0_symbol=meta0[0],
                    token0_decimals=meta0[1],
                    token0_amount_raw=str(amount0),
                    token1_address=key[1],
                    token1_symbol=meta1[0],
                    token1_decimals=meta1[1],
                    token1_amount_raw=str(amount1),
                    fee_tier=fee_tier,
                    tick_lower=tick_lower,
                    tick_upper=tick_upper,
                    liquidity=str(liquidity),
                    in_range=tick_lower <= current_tick < tick_upper,
                )
            )
        if len(positions) != len(entries):
            complete = False
        return positions, warnings, complete

    async def _token_metadata(
        self,
        entries: list[tuple[str, tuple[str, str, int, int, str], int, int, int]],
    ) -> dict[str, tuple[str, int]]:
        addresses = sorted(
            {
                address
                for _token_id, key, _lower, _upper, _liquidity in entries
                for address in (key[0], key[1])
                if address != NATIVE_CURRENCY and address not in self.cache.token_meta
            }
        )
        if addresses:
            calls: list[tuple[str, str]] = []
            for address in addresses:
                calls.append((address, SEL_SYMBOL))
                calls.append((address, SEL_DECIMALS))
            results = await self.transport.call_batch(calls)
            for index, address in enumerate(addresses):
                symbol_data = results[index * 2]
                decimals_data = results[index * 2 + 1]
                symbol = decode_abi_string(symbol_data) if symbol_data else ""
                symbol = symbol.strip()[:32] or address[:8]
                decimals: int | None = None
                if decimals_data and decimals_data not in {"", "0x"}:
                    try:
                        candidate = _abi_words(decimals_data)[0]
                        if 0 <= candidate <= 36:
                            decimals = candidate
                    except (ProviderError, ValueError, IndexError):
                        decimals = None
                if decimals is not None:
                    self.cache.token_meta[address] = (symbol, decimals)
        meta = dict(self.cache.token_meta)
        meta[NATIVE_CURRENCY] = (self.native_symbol, self.native_decimals)
        return meta
