"""Switchboard Mimic — API REST + WebSocket + frontend estático.

Arranque:  .venv/bin/python -m switchboard.main   (o via systemd)
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import PROJECT_ROOT, load_config
from .engine import MimicEngine
from .leds import create_strip
from .modbus_client import ModbusReader
from .store import SegmentStore
from .typestore import RULES, TypeStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("switchboard")

cfg = load_config()
store = SegmentStore(PROJECT_ROOT / cfg["data_file"])
type_store = TypeStore(PROJECT_ROOT / cfg["data_file"].replace("segments", "types"))
strip = create_strip(cfg["led"])
modbus = ModbusReader(
    cfg["modbus"]["host"], cfg["modbus"]["port"], cfg["modbus"]["unit"], cfg["modbus"]["timeout_s"]
)
engine = MimicEngine(
    store, type_store, strip, modbus, cfg["modbus"]["registers_per_element"], cfg["poll_interval_s"]
)

ws_clients: set = set()
main_loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast(state: dict):
    if main_loop is None:
        return
    message = json.dumps({"type": "state", "data": state})
    for ws in list(ws_clients):
        asyncio.run_coroutine_threadsafe(_safe_send(ws, message), main_loop)


async def _safe_send(ws: WebSocket, message: str):
    try:
        await ws.send_text(message)
    except Exception:
        ws_clients.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    engine.on_update = broadcast
    await engine.start()
    log.info("Motor del mímico arrancado (%d LEDs)", strip.count)
    yield
    await engine.stop()


app = FastAPI(title="Switchboard Mimic", lifespan=lifespan)


class SegmentIn(BaseModel):
    start: int
    end: int
    description: str = ""
    type: str = "Incom"
    station: int = 0


class RegisterWrite(BaseModel):
    address: int
    value: int


class TypeIn(BaseModel):
    name: str
    rule: str = "simple"


# ---------- API ----------

@app.get("/api/state")
def get_state():
    return engine.state()


@app.get("/api/segments")
def list_segments():
    return {"segments": store.list(), "types": [t["name"] for t in type_store.list()]}


def _check_type(name: str):
    if not type_store.exists(name):
        raise HTTPException(400, f"el tipo {name!r} no está definido (ver Settings)")


@app.post("/api/segments")
async def add_segment(seg: SegmentIn):
    _check_type(seg.type)
    try:
        row = store.add(seg.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await engine.refresh()
    return row


@app.put("/api/segments/{seg_id}")
async def update_segment(seg_id: int, seg: SegmentIn):
    _check_type(seg.type)
    try:
        row = store.update(seg_id, seg.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "segmento no encontrado")
    await engine.refresh()
    return row


@app.delete("/api/segments/{seg_id}")
async def delete_segment(seg_id: int):
    if not store.delete(seg_id):
        raise HTTPException(404, "segmento no encontrado")
    if engine.selected_id == seg_id:
        engine.selected_id = None
    await engine.refresh()
    return {"ok": True}


@app.delete("/api/segments")
async def clear_segments():
    store.clear()
    engine.selected_id = None
    await engine.refresh()
    return {"ok": True}


# ---------- tipos (Settings) ----------

@app.get("/api/types")
def list_types():
    return {"types": type_store.list(), "rules": RULES}


@app.post("/api/types")
async def add_type(t: TypeIn):
    try:
        row = type_store.add(t.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await engine.refresh()
    return row


@app.put("/api/types/{name}")
async def update_type(name: str, t: TypeIn):
    try:
        row = type_store.update(name, t.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "tipo no encontrado")
    if row["name"] != name:
        store.rename_type(name, row["name"])
    await engine.refresh()
    return row


@app.delete("/api/types/{name}")
async def delete_type(name: str):
    in_use = store.count_by_type(name)
    if in_use:
        raise HTTPException(400, f"el tipo {name!r} está asignado a {in_use} segmento(s)")
    if not type_store.delete(name):
        raise HTTPException(404, "tipo no encontrado")
    return {"ok": True}


@app.post("/api/refresh")
async def manual_refresh():
    await engine.refresh()
    return {"ok": True}


@app.post("/api/test-mode/{enabled}")
def set_test_mode(enabled: bool):
    engine.set_test_mode(enabled)
    return {"test_mode": engine.test_mode}


@app.post("/api/select/{seg_id}")
def select_segment(seg_id: int):
    engine.select_segment(seg_id if seg_id > 0 else None)
    return {"selected_id": engine.selected_id}


@app.post("/api/modbus/write")
async def modbus_write(req: RegisterWrite):
    """Escritura directa de un registro (para pruebas / simulación de estados del PLC)."""
    try:
        await modbus.write_register(req.address, req.value)
    except Exception as exc:
        raise HTTPException(502, f"Modbus: {exc}")
    return {"ok": True}


# ---------- WebSocket ----------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    await ws.send_text(json.dumps({"type": "state", "data": engine.state()}))
    try:
        while True:
            await ws.receive_text()  # solo mantenemos viva la conexión
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


# ---------- Frontend ----------

web_dir = PROJECT_ROOT / "web"
app.mount("/static", StaticFiles(directory=web_dir), name="static")


@app.get("/")
def index():
    return FileResponse(web_dir / "index.html")


@app.get("/settings")
def settings_page():
    return FileResponse(web_dir / "settings.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=cfg["http_port"], log_level="info")
