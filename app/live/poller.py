"""One thread per device: persistent Modbus connection, latest values kept in memory only."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .decoding import decode
from .modbus import ModbusClient, ModbusError, ModbusExceptionResponse
from .model import DeviceDef
from .planning import build_plan

log = logging.getLogger("live.poller")


@dataclass
class DeviceState:
    last_ok: Optional[datetime] = None
    last_attempt: Optional[datetime] = None
    error: Optional[str] = None
    partial: bool = False
    values: dict[str, tuple[float, datetime]] = field(default_factory=dict)


class LiveStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.devices: dict[str, DeviceState] = {}

    def snapshot(self, code: str) -> DeviceState:
        with self.lock:
            s = self.devices.get(code) or DeviceState()
            return DeviceState(s.last_ok, s.last_attempt, s.error, s.partial, dict(s.values))


def poll_once(dev: DeviceDef, client: ModbusClient, store: LiveStore) -> None:
    now = datetime.now(timezone.utc)
    values, errors = {}, []
    for req in build_plan(dev.all_fields(), dev.max_block_gap):
        try:
            if not client.is_connected:
                client.connect()
            regs = client.read_holding_registers(req.address, req.quantity)
        except ModbusExceptionResponse as exc:          # the device answered: keep the connection
            errors.append(str(exc))
            continue
        except ModbusError as exc:
            errors.append(str(exc))
            client.close()
            break                                        # device unreachable: skip the rest this cycle
        for f in req.fields:
            try:
                values[f.id] = (decode(req.slice_for(f, regs), f.data_type, f.word_order) * f.scale, now)
            except (ValueError, IndexError) as exc:
                errors.append(f"{f.label}: {exc}")
    with store.lock:
        s = store.devices.setdefault(dev.code, DeviceState())
        s.last_attempt = now
        s.values.update(values)
        s.error = errors[0] if errors else None
        s.partial = bool(values) and bool(errors)
        if values:
            s.last_ok = now


def run_device(dev: DeviceDef, store: LiveStore, stop: threading.Event) -> None:
    client = ModbusClient(dev.host, dev.port, dev.slave_id, dev.timeout_seconds, dev.transport)
    while not stop.is_set():
        started = time.monotonic()
        try:
            poll_once(dev, client, store)
        except Exception:                                # never let one device stop its thread
            log.exception("%s: poll failed", dev.code)
            client.close()
        stop.wait(max(1.0, dev.poll_seconds - (time.monotonic() - started)))
    client.close()


def start(devices: list[DeviceDef], store: LiveStore) -> threading.Event:
    stop = threading.Event()
    for i, dev in enumerate(devices):
        t = threading.Thread(target=lambda d=dev, k=i: (stop.wait(k * 0.2), run_device(d, store, stop)),
                             name=f"poll-{dev.code}", daemon=True)
        t.start()
    log.info("Polling %d devices", len(devices))
    return stop
