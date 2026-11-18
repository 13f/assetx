from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.chains.base import ChainAdapter, LpPosition
from app.chains.uniswap import NATIVE_CURRENCY
from app.db import Database
from app.services.prices import ContractPriceResult, PriceService
from app.services.repository import load_networks
from app.utils.amounts import amount_from_raw, decimal_to_str, format_usd
from app.utils.time import utcnow_iso


class AddressNotFound(LookupError):
    pass


def _positive(raw: str) -> bool:
    try:
        return int(raw) > 0
    except (TypeError, ValueError):
        return False


def _position_value(
    position: LpPosition,
    price0: Decimal | None,
    price1: Decimal | None,
) -> tuple[Decimal | None, list[str]]:
    """Return the USD value of a position and the symbols that lack a price.

    An empty side of the range does not need a price, so a fully out-of-range
    position can still be valued when only the held token is priced. Native ETH
    in a V4 pool is converted to the chain's native price before this call.
    """
    amount0 = amount_from_raw(position.token0_amount_raw, position.token0_decimals)
    amount1 = amount_from_raw(position.token1_amount_raw, position.token1_decimals)
    value = Decimal(0)
    missing: list[str] = []
    if amount0 > 0:
        if price0 is None:
            missing.append(position.token0_symbol)
        else:
            value += amount0 * price0
    if amount1 > 0:
        if price1 is None:
            missing.append(position.token1_symbol)
        else:
            value += amount1 * price1
    return (None if missing else value), missing


class RefreshService:
    def __init__(self, db: Database, adapters: dict[str, ChainAdapter], prices: PriceService):
        self.db = db
        self.adapters = adapters
        self.prices = prices

    async def refresh_address(self, address_id: int) -> dict[str, Any]:
        address = self.db.fetchone("SELECT * FROM addresses WHERE id = ?", (address_id,))
        if address is None:
            raise AddressNotFound(f"address {address_id} not found")
        adapter = self.adapters.get(address["chain"])
        if adapter is None:
            raise ValueError(f"unsupported chain: {address['chain']}")
        networks = load_networks(self.db, chain=address["chain"])
        if not networks:
            raise ValueError(f"no token networks configured for chain {address['chain']}")

        fetch = await adapter.fetch_balances(address["address"], networks)
        price_result = await self.prices.get_prices([network.token_id for network in networks])
        timestamp = utcnow_iso()
        warnings = list(fetch.warnings)
        if price_result.warning:
            warnings.append(price_result.warning)

        native_network = next((network for network in networks if network.is_native), None)
        native_price = (
            price_result.prices.get(native_network.token_id)
            if native_network is not None
            else None
        )

        contract_prices: ContractPriceResult | None = None
        position_rows: list[
            tuple[LpPosition, Decimal | None, Decimal | None, Decimal | None]
        ] = []
        if fetch.positions:
            contracts = sorted(
                {
                    address
                    for position in fetch.positions
                    for address, raw in (
                        (position.token0_address, position.token0_amount_raw),
                        (position.token1_address, position.token1_amount_raw),
                    )
                    if _positive(raw) and address != NATIVE_CURRENCY
                }
            )
            if contracts:
                contract_prices = await self.prices.get_contract_prices(
                    address["chain"], contracts
                )
                if contract_prices.warning:
                    warnings.append(contract_prices.warning)
            for position in fetch.positions:
                price0 = (
                    contract_prices.prices.get(position.token0_address)
                    if contract_prices is not None
                    else None
                )
                price1 = (
                    contract_prices.prices.get(position.token1_address)
                    if contract_prices is not None
                    else None
                )
                if position.token0_address == NATIVE_CURRENCY:
                    price0 = native_price
                if position.token1_address == NATIVE_CURRENCY:
                    price1 = native_price
                value, missing = _position_value(position, price0, price1)
                if missing:
                    warnings.append(
                        f"LP #{position.token_id}: no price for {'/'.join(missing)}"
                    )
                position_rows.append((position, price0, price1, value))

        network_ids = [network.id for network in networks]
        placeholders = ",".join("?" for _ in network_ids)
        with self.db.transaction() as conn:
            # Remove stale rows if a token network was disabled or removed.
            conn.execute(
                f"DELETE FROM balances WHERE address_id = ? AND token_network_id NOT IN ({placeholders})",
                (address_id, *network_ids),
            )
            for network in networks:
                raw = fetch.balances.get(network.id)
                if raw is None:
                    warnings.append(f"{network.symbol}: provider returned no balance")
                    raw = "0"
                balance = amount_from_raw(raw, network.decimals)
                price = price_result.prices.get(network.token_id)
                value = (balance * price) if price is not None else None
                conn.execute(
                    """
                    INSERT INTO balances
                        (address_id, token_network_id, raw_balance, price_usd, value_usd, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(address_id, token_network_id) DO UPDATE SET
                        raw_balance = excluded.raw_balance,
                        price_usd = excluded.price_usd,
                        value_usd = excluded.value_usd,
                        updated_at = excluded.updated_at
                    """,
                    (
                        address_id,
                        network.id,
                        str(raw),
                        decimal_to_str(price),
                        format_usd(value),
                        timestamp,
                    ),
                )
            completed_protocols = fetch.positions_complete
            if completed_protocols:
                # A completed protocol scan is authoritative: replace only that
                # protocol's saved rows. A V4 indexer outage therefore never
                # deletes V3 positions, and vice versa.
                for protocol in sorted(completed_protocols):
                    conn.execute(
                        "DELETE FROM nft_positions WHERE address_id = ? AND protocol = ?",
                        (address_id, protocol),
                    )
                for position, price0, price1, value in position_rows:
                    if position.protocol not in completed_protocols:
                        continue
                    conn.execute(
                        """
                        INSERT INTO nft_positions
                            (address_id, chain, protocol, collection, contract_address,
                             token_id, pool_address, token0_address, token0_symbol,
                             token0_decimals, token0_amount_raw, token1_address,
                             token1_symbol, token1_decimals, token1_amount_raw,
                             fee_tier, tick_lower, tick_upper, liquidity, in_range,
                             token0_price_usd, token1_price_usd, value_usd, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            address_id,
                            address["chain"],
                            position.protocol,
                            position.collection,
                            position.contract_address,
                            position.token_id,
                            position.pool_address,
                            position.token0_address,
                            position.token0_symbol,
                            position.token0_decimals,
                            position.token0_amount_raw,
                            position.token1_address,
                            position.token1_symbol,
                            position.token1_decimals,
                            position.token1_amount_raw,
                            position.fee_tier,
                            position.tick_lower,
                            position.tick_upper,
                            position.liquidity,
                            1 if position.in_range else 0,
                            decimal_to_str(price0),
                            decimal_to_str(price1),
                            format_usd(value),
                            timestamp,
                        ),
                    )
            if price_result.prices and price_result.fetched_at:
                for token_id, price in price_result.prices.items():
                    conn.execute(
                        """
                        INSERT INTO prices(token_id, price_usd, source, fetched_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(token_id) DO UPDATE SET
                            price_usd = excluded.price_usd,
                            source = excluded.source,
                            fetched_at = excluded.fetched_at
                        """,
                        (
                            token_id,
                            decimal_to_str(price),
                            price_result.source or "unknown",
                            price_result.fetched_at,
                        ),
                    )
            if (
                contract_prices is not None
                and contract_prices.prices
                and contract_prices.fetched_at
            ):
                for contract, price in contract_prices.prices.items():
                    conn.execute(
                        """
                        INSERT INTO contract_prices
                            (chain, contract_address, price_usd, source, fetched_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(chain, contract_address) DO UPDATE SET
                            price_usd = excluded.price_usd,
                            source = excluded.source,
                            fetched_at = excluded.fetched_at
                        """,
                        (
                            address["chain"],
                            contract,
                            decimal_to_str(price),
                            contract_prices.source or "unknown",
                            contract_prices.fetched_at,
                        ),
                    )
            warning_text = "; ".join(dict.fromkeys(warnings))[:1000] or None
            conn.execute(
                """
                UPDATE addresses
                SET last_refreshed_at = ?, last_refresh_error = NULL,
                    last_refresh_warning = ?, last_refresh_provider = ?, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, warning_text, fetch.provider, timestamp, address_id),
            )
        return {
            "address_id": address_id,
            "provider": fetch.provider,
            "warning": warning_text,
            "token_count": len(networks),
            "position_count": sum(
                1
                for position, _price0, _price1, _value in position_rows
                if position.protocol in completed_protocols
            ),
        }
