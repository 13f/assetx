from __future__ import annotations

from typing import Any

from app.chains.base import ChainAdapter
from app.db import Database
from app.services.prices import PriceService
from app.services.repository import load_networks
from app.utils.amounts import amount_from_raw, decimal_to_str, format_usd
from app.utils.time import utcnow_iso


class AddressNotFound(LookupError):
    pass


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
        }
