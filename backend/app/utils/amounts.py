from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def amount_from_raw(raw: str | int, decimals: int) -> Decimal:
    """Convert an integer base-unit amount into human units without floats."""
    if decimals < 0:
        raise ValueError("decimals must be >= 0")
    try:
        return Decimal(str(raw)).scaleb(-decimals)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid raw amount: {raw!r}") from exc


def decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized, "f").split(".")[0]
    return format(normalized, "f")


def format_usd(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def format_price(value: Decimal | None) -> str | None:
    if value is None:
        return None
    # Keep more precision for low-priced assets such as CKB.
    if value >= Decimal("1"):
        quant = Decimal("0.000001")
    elif value >= Decimal("0.01"):
        quant = Decimal("0.00000001")
    else:
        quant = Decimal("0.0000000001")
    return decimal_to_str(value.quantize(quant, rounding=ROUND_HALF_UP))


_SCI_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def parse_decimal(value: str | int | float | None) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, float):
        value = str(value)
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc
