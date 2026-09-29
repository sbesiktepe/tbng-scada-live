"""Read plan: which fields are read by which Modbus request.

If max_block_gap is None every field gets its own request (field-verified ELGAS
behaviour; reading undefined registers in between may return an exception on some
devices). If it is a number, fields separated by at most that many unused
registers are merged into one request (ABB / R1520 template: 0..15, one request
of 16 registers).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .model import FieldDef

MAX_QUANTITY = 125


@dataclass(frozen=True)
class ReadRequest:
    address: int
    quantity: int
    fields: tuple[FieldDef, ...]

    def slice_for(self, f: FieldDef, registers: list[int]) -> list[int]:
        start = f.address - self.address
        return registers[start:start + f.quantity]


def build_plan(fields: Iterable[FieldDef], max_block_gap: Optional[int]) -> list[ReadRequest]:
    readable = sorted((f for f in fields if f.readable), key=lambda f: (f.address, f.quantity))
    if max_block_gap is None:
        return [ReadRequest(f.address, f.quantity, (f,)) for f in readable]

    plan: list[ReadRequest] = []
    group: list[FieldDef] = []
    start = end = 0  # end: exclusive
    for f in readable:
        f_end = f.address + f.quantity
        if group and f.address - end <= max_block_gap and max(end, f_end) - start <= MAX_QUANTITY:
            group.append(f)
            end = max(end, f_end)
            continue
        if group:
            plan.append(ReadRequest(start, end - start, tuple(group)))
        group, start, end = [f], f.address, f_end
    if group:
        plan.append(ReadRequest(start, end - start, tuple(group)))
    return plan
