from __future__ import annotations

import hashlib

C32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_C32_INDEX = {char: index for index, char in enumerate(C32_ALPHABET)}

# Stacks mainnet versions. 22 is a single-signature wallet (SP...), 20 is a
# multisig wallet (SM...). Testnet uses 26 (ST...) and 21 (SN...).
STACKS_VERSION_P2PKH = 22
STACKS_VERSION_P2SH = 20
STACKS_MAINNET_VERSIONS = frozenset({STACKS_VERSION_P2PKH, STACKS_VERSION_P2SH})

_PAYLOAD_BYTES = 20
_CHECKSUM_BYTES = 4


class C32Error(ValueError):
    """Raised when a c32check Stacks address or its checksum is invalid."""


def c32_normalize(text: str) -> str:
    """Uppercase a c32 string and map Crockford's ambiguous input characters."""
    return text.strip().upper().replace("O", "0").replace("L", "1").replace("I", "1")


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _encode_number(value: int) -> str:
    if value == 0:
        return C32_ALPHABET[0]
    digits: list[str] = []
    while value:
        value, remainder = divmod(value, 32)
        digits.append(C32_ALPHABET[remainder])
    return "".join(reversed(digits))


def encode_stacks_address(version: int, payload: bytes) -> str:
    """Encode a 20-byte hash160 as a c32check address.

    Stacks addresses are ``S`` + the c32 character for the version byte + a
    base-32 big-endian encoding of ``payload || checksum``. Leading zero bytes
    in that buffer are rendered as literal ``0`` characters, which is why
    addresses such as the burn address are much shorter than the usual 41
    characters.
    """
    if version not in STACKS_MAINNET_VERSIONS:
        raise C32Error(f"unsupported Stacks address version: {version}")
    if len(payload) != _PAYLOAD_BYTES:
        raise C32Error(f"Stacks addresses require a {_PAYLOAD_BYTES}-byte hash160")
    checksum = _double_sha256(bytes([version]) + payload)[:_CHECKSUM_BYTES]
    buffer = payload + checksum
    leading_zero_bytes = len(buffer) - len(buffer.lstrip(b"\x00"))
    digits = _encode_number(int.from_bytes(buffer, "big"))
    return "S" + C32_ALPHABET[version] + (C32_ALPHABET[0] * leading_zero_bytes) + digits


def decode_stacks_address(address: str) -> tuple[int, bytes]:
    """Decode and checksum-verify a c32check Stacks address."""
    value = c32_normalize(address)
    if len(value) < 3:
        raise C32Error("address is too short")
    if value[0] != "S":
        raise C32Error('c32check addresses must start with "S"')
    version_char = value[1]
    if version_char not in _C32_INDEX:
        raise C32Error(f"invalid version character: {version_char!r}")
    version = _C32_INDEX[version_char]
    if version not in STACKS_MAINNET_VERSIONS:
        raise C32Error("only Stacks mainnet addresses (SP.../SM...) are supported")

    body = value[2:]
    if any(char not in _C32_INDEX for char in body):
        raise C32Error("address contains characters outside the c32 alphabet")

    number = 0
    for char in body:
        number = number * 32 + _C32_INDEX[char]
    try:
        raw = number.to_bytes(_PAYLOAD_BYTES + _CHECKSUM_BYTES, "big")
    except OverflowError as exc:
        raise C32Error("address payload is too long") from exc

    payload, checksum = raw[:_PAYLOAD_BYTES], raw[_PAYLOAD_BYTES:]
    expected = _double_sha256(bytes([version]) + payload)[:_CHECKSUM_BYTES]
    if checksum != expected:
        raise C32Error("checksum mismatch")
    if encode_stacks_address(version, payload) != value:
        raise C32Error("address is not canonically encoded")
    return version, payload


def normalize_stacks_address(address: str) -> str:
    """Return the canonical uppercase form of a valid Stacks address."""
    decode_stacks_address(address)
    return c32_normalize(address)
