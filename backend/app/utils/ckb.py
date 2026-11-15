from __future__ import annotations

from dataclasses import dataclass

from app.utils.bech32 import Bech32Error, bech32_decode_bytes

SECP256K1_CODE_HASH = "0x9bd7e06f3ecf4be0f2fcd2188b23f1b9fcc88e5d4b65a8637b17723bbda3cce8"
MULTISIG_CODE_HASH = "0x5c5069eb0857efc65e1bca0c07df34c31663b3622fd3876c876320fc9634e2a8"
ANYONE_CAN_PAY_CODE_HASH = "0xd369597ff47f29fbc0d47d2e3775370d1250b85140c670e4718af712983a2354"

SHORT_CODE_HASHES: dict[int, tuple[str, str]] = {
    0: (SECP256K1_CODE_HASH, "type"),
    1: (MULTISIG_CODE_HASH, "type"),
    2: (ANYONE_CAN_PAY_CODE_HASH, "type"),
}

HASH_TYPES = {0: "data", 1: "type", 2: "data1", 3: "data2"}


class CkbAddressError(ValueError):
    pass


@dataclass(frozen=True)
class CkbLockScript:
    code_hash: str
    hash_type: str
    args: str

    def as_rpc(self) -> dict[str, str]:
        return {
            "code_hash": self.code_hash,
            "hash_type": self.hash_type,
            "args": self.args,
        }


def decode_ckb_lock(address: str) -> CkbLockScript:
    try:
        payload, spec = bech32_decode_bytes(address, "ckb")
    except Bech32Error as exc:
        raise CkbAddressError(str(exc)) from exc
    if not payload:
        raise CkbAddressError("empty CKB address payload")
    version = payload[0]
    if version == 0x00:
        if spec != "bech32m":
            raise CkbAddressError("full CKB payload must use bech32m")
        if len(payload) < 34:
            raise CkbAddressError("CKB full payload is too short")
        code_hash = "0x" + payload[1:33].hex()
        hash_type_byte = payload[33]
        if hash_type_byte not in HASH_TYPES:
            raise CkbAddressError("unsupported CKB hash type")
        return CkbLockScript(code_hash, HASH_TYPES[hash_type_byte], "0x" + payload[34:].hex())
    if version == 0x01:
        if spec != "bech32":
            raise CkbAddressError("short CKB payload must use bech32")
        if len(payload) < 3:
            raise CkbAddressError("CKB short payload is too short")
        index = payload[1]
        try:
            code_hash, hash_type = SHORT_CODE_HASHES[index]
        except KeyError as exc:
            raise CkbAddressError(f"unknown CKB code hash index: {index}") from exc
        return CkbLockScript(code_hash, hash_type, "0x" + payload[2:].hex())
    if version in (0x02, 0x04):
        if spec != "bech32":
            raise CkbAddressError("legacy CKB payload must use bech32")
        if len(payload) < 33:
            raise CkbAddressError("legacy CKB payload is too short")
        code_hash = "0x" + payload[1:33].hex()
        hash_type = "data" if version == 0x02 else "type"
        return CkbLockScript(code_hash, hash_type, "0x" + payload[33:].hex())
    raise CkbAddressError(f"unsupported CKB address format: 0x{version:02x}")
