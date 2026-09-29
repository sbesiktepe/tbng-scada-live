"""Register -> value decoding.

Word order:
  ABCD  no word swap. ELGAS/ELCORplus (verified in the field):
        FLT = unpack(">f", pack(">HH", r0, r1)), LNG = (r0 << 16) | r1
  CDAB  16-bit word swap. Legacy Cinterion/ABB reading (BitConverter.toSingle):
        Modbus bytes A B C D -> IEEE754 bits C D A B
"""
from __future__ import annotations

import struct

REGISTER_COUNT = {
    "INT16": 1,
    "UINT16": 1,
    "FLT": 2,
    "LNG": 2,
    "INT32": 2,
    "LNG_DIFF": 4,
}


def register_count(data_type: str) -> int:
    try:
        return REGISTER_COUNT[data_type]
    except KeyError:
        raise ValueError(f"Unsupported data type: {data_type}") from None


def _words(pair: list[int], word_order: str) -> tuple[int, int]:
    if len(pair) != 2:
        raise ValueError("A 32-bit value needs 2 registers")
    if word_order == "ABCD":
        return pair[0], pair[1]
    if word_order == "CDAB":
        return pair[1], pair[0]
    raise ValueError(f"Unsupported word order: {word_order}")


def _u32(pair: list[int], word_order: str) -> int:
    hi, lo = _words(pair, word_order)
    return ((hi & 0xFFFF) << 16) | (lo & 0xFFFF)


def decode(registers: list[int], data_type: str, word_order: str = "ABCD") -> float:
    expected = register_count(data_type)
    if len(registers) != expected:
        raise ValueError(f"{data_type} {expected} registers required, got {len(registers)}")

    if data_type == "UINT16":
        return float(registers[0] & 0xFFFF)
    if data_type == "INT16":
        return float(struct.unpack(">h", struct.pack(">H", registers[0] & 0xFFFF))[0])
    if data_type == "FLT":
        return float(struct.unpack(">f", struct.pack(">I", _u32(registers, word_order)))[0])
    if data_type == "LNG":
        return float(_u32(registers, word_order))
    if data_type == "INT32":
        return float(struct.unpack(">i", struct.pack(">I", _u32(registers, word_order)))[0])
    if data_type == "LNG_DIFF":
        # Meter archive: first 2 registers = cumulative of the last closed period,
        # next 2 registers = cumulative of the period before (verified with Modbus Poll).
        # A negative difference (correction archive behaviour) is not a valid consumption -> 0.
        latest = _u32(registers[0:2], word_order)
        previous = _u32(registers[2:4], word_order)
        return float(max(latest - previous, 0))
    raise ValueError(f"Unsupported data type: {data_type}")
