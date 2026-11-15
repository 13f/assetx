from __future__ import annotations

import re

from app.utils.base58 import Base58Error, b58check_decode, b58decode
from app.utils.bech32 import (
    Bech32Error,
    bech32_decode,
    bech32_decode_bytes,
    convertbits,
)
from app.utils.ckb import CkbAddressError, decode_ckb_lock

EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
COSMOS_DENOM_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9/:._-]{1,127}$")


class AddressValidationError(ValueError):
    pass


def _eth_address(address: str) -> str:
    value = address.strip()
    if not EVM_ADDRESS_RE.fullmatch(value):
        raise AddressValidationError("Ethereum addresses must be 0x followed by 40 hex characters")
    return value.lower()


def _solana_address(address: str) -> str:
    value = address.strip()
    if len(value) < 32 or len(value) > 44:
        raise AddressValidationError("Solana addresses must be 32-44 base58 characters")
    try:
        payload = b58decode(value)
    except Base58Error as exc:
        raise AddressValidationError(f"invalid Solana address: {exc}") from exc
    if len(payload) != 32:
        raise AddressValidationError("Solana addresses must decode to exactly 32 bytes")
    return value


def _bitcoin_address(address: str) -> str:
    value = address.strip()
    if not value:
        raise AddressValidationError("Bitcoin address is required")
    if value.lower().startswith("bc1"):
        try:
            hrp, data, spec = bech32_decode(value)
        except Bech32Error as exc:
            raise AddressValidationError(f"invalid Bitcoin address: {exc}") from exc
        if hrp != "bc":
            raise AddressValidationError("only Bitcoin mainnet (bc1...) addresses are supported")
        if not data:
            raise AddressValidationError("invalid Bitcoin witness address")
        version = data[0]
        if version > 16:
            raise AddressValidationError("invalid Bitcoin witness version")
        if version == 0 and spec != "bech32":
            raise AddressValidationError("Bitcoin v0 addresses must use bech32")
        if version > 0 and spec != "bech32m":
            raise AddressValidationError("Bitcoin v1+ addresses must use bech32m")
        try:
            program = bytes(convertbits(data[1:], 5, 8, pad=False))
        except Bech32Error as exc:
            raise AddressValidationError(f"invalid Bitcoin witness program: {exc}") from exc
        if not 2 <= len(program) <= 40:
            raise AddressValidationError("invalid Bitcoin witness program length")
        if version == 0 and len(program) not in (20, 32):
            raise AddressValidationError("Bitcoin v0 programs must be 20 or 32 bytes")
        return value.lower()
    try:
        payload = b58check_decode(value)
    except Base58Error as exc:
        raise AddressValidationError(f"invalid Bitcoin address: {exc}") from exc
    if len(payload) != 21 or payload[0] not in (0x00, 0x05):
        raise AddressValidationError("only Bitcoin mainnet P2PKH/P2SH addresses are supported")
    return value


def _cosmos_address(address: str) -> str:
    value = address.strip().lower()
    try:
        payload, spec = bech32_decode_bytes(value, "cosmos")
    except Bech32Error as exc:
        raise AddressValidationError(f"invalid Cosmos address: {exc}") from exc
    if spec != "bech32":
        raise AddressValidationError("Cosmos addresses must use bech32")
    if len(payload) not in (20, 32):
        raise AddressValidationError("Cosmos addresses must contain a 20 or 32 byte payload")
    return value


def _nervos_address(address: str) -> str:
    value = address.strip().lower()
    try:
        decode_ckb_lock(value)
    except CkbAddressError as exc:
        raise AddressValidationError(f"invalid Nervos CKB address: {exc}") from exc
    return value


_VALIDATORS = {
    "ethereum": _eth_address,
    "solana": _solana_address,
    "bitcoin": _bitcoin_address,
    "nervos": _nervos_address,
    "cosmos": _cosmos_address,
}


def normalize_address(chain: str, address: str) -> str:
    try:
        validator = _VALIDATORS[chain]
    except KeyError as exc:
        raise AddressValidationError(f"unsupported chain: {chain}") from exc
    return validator(address)


def validate_contract_identifier(chain: str, value: str) -> str:
    """Validate a token identifier for a chain.

    EVM: 20-byte contract address. Solana: 32-byte mint address. Cosmos: bank
    denom (native denom or IBC denom). Bitcoin/Nervos do not support generic
    token contracts in AssetX.
    """
    value = value.strip()
    if chain == "ethereum":
        if not EVM_ADDRESS_RE.fullmatch(value):
            raise AddressValidationError("ERC-20 contract must be a 0x-prefixed 20-byte address")
        return value.lower()
    if chain == "solana":
        try:
            payload = b58decode(value)
        except Base58Error as exc:
            raise AddressValidationError(f"invalid Solana mint address: {exc}") from exc
        if len(payload) != 32:
            raise AddressValidationError("Solana mint addresses must decode to exactly 32 bytes")
        return value
    if chain == "cosmos":
        if not COSMOS_DENOM_RE.fullmatch(value):
            raise AddressValidationError("Cosmos token identifiers must be a bank denom such as uatom or ibc/...")
        return value
    if chain in {"bitcoin", "nervos"}:
        raise AddressValidationError(f"{chain} does not support generic token contracts in AssetX")
    raise AddressValidationError(f"unsupported chain: {chain}")
