"""TBNG SCADA Live - emergency live viewer.

Polls every device in config/devices.yaml directly (Modbus, read-only, function 03)
and shows only the latest values. No database, no history, no alarms. Sign-in is
done by Caddy (one shared account).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import poller
from .model import load_devices

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("live")

DEVICES_FILE = Path(os.getenv("DEVICES_FILE", "/config/devices.yaml"))
# Mobile data: the meters' lines are metered. 30 s is enough for an emergency view.
MIN_POLL_SECONDS = int(os.getenv("MIN_POLL_SECONDS", "30"))
STATIC = Path(__file__).parent / "static"

devices = load_devices(DEVICES_FILE, MIN_POLL_SECONDS)
store = poller.LiveStore()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = poller.start(devices, store)
    yield
    stop.set()


app = FastAPI(title="TBNG SCADA Live", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/health")
def health():
    return {"ok": True, "devices": len(devices)}


@app.get("/api/cards")
def cards():
    now = datetime.now(timezone.utc)
    out = []
    for d in devices:
        s = store.snapshot(d.code)
        age = (now - s.last_ok).total_seconds() if s.last_ok else None
        status = ("waiting" if s.last_attempt is None else
                  "passive" if age is None or age > d.passive_seconds else
                  "alarm" if s.partial or s.error else "normal")
        for c in d.cards:
            out.append({
                "code": c.code, "name": c.name, "domain": c.domain, "category": c.category, "region": c.region,
                "channel": c.channel, "status": status, "error": s.error, "lastOk": s.last_ok,
                "fields": [
                    {"label": f.label, "unit": f.unit, "decimals": f.decimals, "role": f.summary_role,
                     "value": s.values.get(f.id, (None, None))[0], "readAt": s.values.get(f.id, (None, None))[1]}
                    for f in c.fields if f.show_on_card
                ],
            })
    return {"now": now, "pollSeconds": MIN_POLL_SECONDS, "cards": out}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
