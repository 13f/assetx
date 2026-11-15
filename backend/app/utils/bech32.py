from __future__ import annotations

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
CHARSET_MAP = {char: index for index, char in enumerate(CHARSET)}
BECH32_CONST = 1
BECH32M_CONST = 0x2BC830A3


class Bech32Error(ValueError):
    pass


def _polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index in range(5):
            if (top >> index) & 1:
                checksum ^= generator[index]
    return checksum


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]


def convertbits(data: bytes | list[int], from_bits: int, to_bits: int, pad: bool = True) -> list[int]:
    accumulator = 0
    bits = 0
    result: list[int] = []
    max_value = (1 << to_bits) - 1
    max_accumulator = (1 << (from_bits + to_bits - 1)) - 1
    for value in data:
        if value < 0 or value >> from_bits:
            raise Bech32Error("invalid data value for base conversion")
        accumulator = ((accumulator << from_bits) | value) & max_accumulator
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            result.append((accumulator >> bits) & max_value)
    if pad:
        if bits:
            result.append((accumulator << (to_bits - bits)) & max_value)
    elif bits >= from_bits or ((accumulator << (to_bits - bits)) & max_value):
        raise Bech32Error("invalid padding in bech32 data")
    return result


def bech32_encode(hrp: str, data: list[int], spec: str = "bech32") -> str:
    constant = BECH32M_CONST if spec == "bech32m" else BECH32_CONST
    values = _hrp_expand(hrp) + data
    polymod = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ constant
    checksum = [(polymod >> 5 * (5 - index)) & 31 for index in range(6)]
    return hrp + "1" + "".join(CHARSET[value] for value in data + checksum)


def bech32_decode(value: str) -> tuple[str, list[int], str]:
    if not value:
        raise Bech32Error("empty bech32 string")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise Bech32Error("bech32 string contains invalid characters")
    if value.lower() != value and value.upper() != value:
        raise Bech32Error("bech32 string may not mix cases")
    value = value.lower()
    separator = value.rfind("1")
    if separator < 1 or separator + 7 > len(value):
        raise Bech32Error("invalid bech32 separator position")
    hrp = value[:separator]
    data_part = value[separator + 1 :]
    try:
        data = [CHARSET_MAP[char] for char in data_part]
    except KeyError as exc:
        raise Bech32Error(f"invalid bech32 character: {exc.args[0]!r}") from exc
    check = _polymod(_hrp_expand(hrp) + data)
    if check == BECH32_CONST:
        spec = "bech32"
    elif check == BECH32M_CONST:
        spec = "bech32m"
    else:
        raise Bech32Error("invalid bech32 checksum")
    return hrp, data[:-6], spec


def bech32_decode_bytes(value: str, expected_hrp: str) -> tuple[bytes, str]:
    hrp, data, spec = bech32_decode(value)
    if hrp != expected_hrp:
        raise Bech32Error(f"expected {expected_hrp!r} address prefix, got {hrp!r}")
    payload = bytes(convertbits(data, 5, 8, pad=False))
    return payload, spec
