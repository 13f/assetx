"""Keccak-256 as used by Ethereum.

``hashlib.sha3_256`` implements the NIST SHA-3 variant, which differs from
Keccak-256 in its padding byte. Ethereum uses the original Keccak padding, so
the small pure-Python permutation below is needed for ABI selectors, event
topics, and ``poolId`` derivation. The function is only called a handful of
times per refresh, so a dependency-free implementation is preferable to adding
a crypto package.
"""

from __future__ import annotations

_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_ROTATION = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)
_MASK = (1 << 64) - 1
_RATE = 136


def _rotl(value: int, shift: int) -> int:
    if shift == 0:
        return value
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _permute(state: list[int]) -> None:
    for round_constant in _ROUND_CONSTANTS:
        columns = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        delta = [
            columns[(x - 1) % 5] ^ _rotl(columns[(x + 1) % 5], 1) for x in range(5)
        ]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= delta[x]
        lanes = [0] * 25
        for x in range(5):
            for y in range(5):
                lanes[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(
                    state[x + 5 * y], _ROTATION[x][y]
                )
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = lanes[x + 5 * y] ^ (
                    (~lanes[(x + 1) % 5 + 5 * y]) & lanes[(x + 2) % 5 + 5 * y]
                )
        state[0] ^= round_constant


def keccak256(data: bytes) -> bytes:
    """Return the 32-byte Keccak-256 digest of ``data``."""
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % _RATE != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    state = [0] * 25
    for offset in range(0, len(padded), _RATE):
        block = padded[offset : offset + _RATE]
        for index in range(_RATE // 8):
            state[index] ^= int.from_bytes(block[index * 8 : index * 8 + 8], "little")
        _permute(state)

    output = bytearray()
    while len(output) < 32:
        for index in range(_RATE // 8):
            output.extend(state[index].to_bytes(8, "little"))
        if len(output) < 32:
            _permute(state)
    return bytes(output[:32])


def selector(signature: str) -> str:
    """Return the 4-byte function selector for a Solidity signature."""
    return "0x" + keccak256(signature.encode()).hex()[:8]
