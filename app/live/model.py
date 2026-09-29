"""Device model of the live viewer, loaded from config/devices.yaml (no database)."""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Optional

import yaml

from .decoding import register_count

MODICON_BASE = 40001


@dataclass(frozen=True)
class FieldDef:
    id: str                       # "<card code>/<key>"
    key: str
    label: str
    unit: str
    register: Optional[int]
    register_notation: str
    data_type: Optional[str]
    word_order: str
    scale: float
    decimals: int
    summary_role: Optional[str]
    show_on_card: bool

    @property
    def readable(self) -> bool:
        return self.register is not None and self.data_type is not None

    @property
    def address(self) -> int:
        """0-based raw Modbus address."""
        assert self.register is not None
        if self.register_notation == "modicon":
            if self.register < MODICON_BASE:
                raise ValueError(f"Invalid Modicon holding register: {self.register}")
            return self.register - MODICON_BASE
        return self.register

    @property
    def quantity(self) -> int:
        assert self.data_type is not None
        return register_count(self.data_type)


@dataclass(frozen=True)
class CardDef:
    code: str
    name: str
    domain: str
    category: str
    region: Optional[str]
    channel: Optional[int]
    fields: tuple[FieldDef, ...]


@dataclass(frozen=True)
class DeviceDef:
    code: str
    name: str
    host: str
    port: int
    slave_id: int
    transport: str
    max_block_gap: Optional[int]
    poll_seconds: int
    timeout_seconds: float
    passive_seconds: int
    cards: tuple[CardDef, ...] = dc_field(default_factory=tuple)

    def all_fields(self) -> list[FieldDef]:
        return [f for c in self.cards for f in c.fields]


def _field(card_code: str, f: dict[str, Any]) -> FieldDef:
    return FieldDef(
        id=f"{card_code}/{f['key']}", key=f["key"], label=f.get("label") or f["key"], unit=f.get("unit") or "",
        register=f.get("register"), register_notation=f.get("register_notation") or "modicon",
        data_type=f.get("data_type"), word_order=f.get("word_order") or "ABCD", scale=float(f.get("scale") or 1),
        decimals=int(f.get("decimals") if f.get("decimals") is not None else 2),
        summary_role=f.get("summary_role"), show_on_card=bool(f.get("show_on_card", True)),
    )


def load_devices(path: Path, min_poll_seconds: int) -> list[DeviceDef]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for d in doc.get("devices") or []:
        cards = tuple(
            CardDef(code=c["code"], name=c.get("name") or c["code"], domain=c.get("domain") or "sales",
                    category=c.get("category") or "", region=c.get("region"), channel=c.get("channel"),
                    fields=tuple(_field(c["code"], f) for f in c.get("fields") or []))
            for c in d.get("cards") or []
        )
        out.append(DeviceDef(
            code=d["code"], name=d.get("name") or d["code"], host=d["host"], port=int(d["port"]),
            slave_id=int(d.get("slave_id", 1)), transport=d.get("transport") or "rtu_over_tcp",
            max_block_gap=d.get("max_block_gap"),
            poll_seconds=max(int(d.get("poll_seconds") or 10), min_poll_seconds),
            timeout_seconds=float(d.get("timeout_seconds") or 5),
            passive_seconds=max(int(d.get("passive_seconds") or 60), 3 * min_poll_seconds),
            cards=cards,
        ))
    return out
