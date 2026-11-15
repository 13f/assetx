from __future__ import annotations

import hashlib

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ALPHABET_MAP = {char: index for index, char in enumerate(ALPHABET)}


class Base58Error(ValueError):
    pass


def b58decode(value: str) -> bytes:
    if not value:
        raise Base58Error("empty base58 string")
    number = 0
    for char in value:
        try:
            digit = ALPHABET_MAP[char]
        except KeyError as exc:
            raise Base58Error(f"invalid base58 character: {char!r}") from exc
        number = number * 58 + digit
    payload = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeros + payload


def b58encode(payload: bytes) -> str:
    number = int.from_bytes(payload, "big")
    encoded = ""
    while number:
        number, digit = divmod(number, 58)
        encoded = ALPHABET[digit] + encoded
    leading_zeros = len(payload) - len(payload.lstrip(b"\x00"))
    return "1" * leading_zeros + encoded


def b58check_decode(value: str) -> bytes:
    payload = b58decode(value)
    if len(payload) < 5:
        raise Base58Error("base58check payload too short")
    body, checksum = payload[:-4], payload[-4:]
    expected = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    if checksum != expected:
        raise Base58Error("invalid base58check checksum")
    return body


def b58check_encode(body: bytes) -> str:
    checksum = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    return b58encode(body + checksum)
