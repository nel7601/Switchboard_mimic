"""Switchboard Mimic — REST API + WebSocket + static frontend.

Start with:  .venv/bin/python -m switchboard.main   (or via systemd)
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import PROJECT_ROOT, load_config
from .elementstore import ElementStore
from .engine import MimicEngine
from .leds import StripManager
from .modbus_client import ModbusPool
from .store import SegmentStore
from .stripstore import WLED_DEFAULT_PORT, StripStore
from .typestore import RULES, TypeStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("switchboard")

cfg = load_config()
store = SegmentStore(PROJECT_ROOT / cfg["data_file"])
type_store = TypeStore(PROJECT_ROOT / cfg["data_file"].replace("segments", "types"))
element_store = ElementStore(PROJECT_ROOT / cfg["data_file"].replace("segments", "elements"))
strip_store = StripStore(PROJECT_ROOT / cfg["data_file"].replace("segments", "strips"), cfg["strips"])
manager = StripManager(cfg["strips"], strip_store)
modbus = ModbusPool(cfg["modbus"]["timeout_s"])
engine = MimicEngine(
    store, element_store, type_store, strip_store, manager, modbus,
    cfg["modbus"]["registers_per_element"], cfg["poll_interval_s"],
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
    log.info(
        "Mimic engine started (%s)",
        ", ".join(
            f"{s['name']} [{s['kind']}]: {manager.hw_count(s['id'])} LEDs"
            for s in strip_store.list()
        ),
    )
    yield
    await engine.stop()


app = FastAPI(title="Switchboard Mimic", lifespan=lifespan)


class SegmentIn(BaseModel):
    start: int
    end: int
    element_id: int
    strip: int = 1


class ModbusParams(BaseModel):
    host: str = "127.0.0.1"
    port: int = 502
    unit: int = 1
    address: int = 0


class ElementIn(BaseModel):
    name: str
    type: str
    modbus: ModbusParams = ModbusParams()


class TypeIn(BaseModel):
    name: str
    rule: str = "simple"


class WledStripIn(BaseModel):
    name: str
    host: str
    port: int = WLED_DEFAULT_PORT
    count: int = 60


class StripUpdate(BaseModel):
    name: str
    host: Optional[str] = None
    port: Optional[int] = None
    count: Optional[int] = None


class RegisterWrite(BaseModel):
    address: int
    value: int
    host: Optional[str] = None
    port: Optional[int] = None
    unit: Optional[int] = None


# ---------- state ----------

@app.get("/api/state")
def get_state():
    return engine.state()


# ---------- segments (Mimic view) ----------

@app.get("/api/segments")
def list_segments():
    return {"segments": store.list(), "elements": element_store.list()}


def _check_element(elem_id: int):
    if element_store.get(elem_id) is None:
        raise HTTPException(400, f"element id={elem_id} is not defined (see Elements)")


def _check_strip(strip: int):
    if not strip_store.exists(strip):
        raise HTTPException(400, f"strip id={strip} does not exist")


@app.post("/api/segments")
async def add_segment(seg: SegmentIn):
    _check_element(seg.element_id)
    _check_strip(seg.strip)
    try:
        row = store.add(seg.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await engine.refresh()
    return row


@app.put("/api/segments/{seg_id}")
async def update_segment(seg_id: int, seg: SegmentIn):
    _check_element(seg.element_id)
    _check_strip(seg.strip)
    try:
        row = store.update(seg_id, seg.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "segment not found")
    await engine.refresh()
    return row


@app.delete("/api/segments/{seg_id}")
async def delete_segment(seg_id: int):
    if not store.delete(seg_id):
        raise HTTPException(404, "segment not found")
    if engine.selected_id == seg_id:
        engine.selected_id = None
    await engine.refresh()
    return {"ok": True}


@app.delete("/api/segments")
async def clear_segments(strip: Optional[int] = None):
    """Clear the whole table, or a single strip's segments with ?strip=N."""
    if strip is not None:
        _check_strip(strip)
    store.clear(strip)
    engine.selected_id = None
    await engine.refresh()
    return {"ok": True}


# ---------- elements ----------

@app.get("/api/elements")
def list_elements():
    types = {t["name"]: t["rule"] for t in type_store.list()}
    rows = []
    for e in element_store.list():
        row = dict(e)
        row["rule"] = types.get(e["type"], "simple")
        row["used_by"] = store.count_by_element(e["id"])
        rows.append(row)
    return {"elements": rows, "types": type_store.list()}


@app.post("/api/elements")
async def add_element(elem: ElementIn):
    if not type_store.exists(elem.type):
        raise HTTPException(400, f"type {elem.type!r} is not defined (see Settings)")
    try:
        row = element_store.add(elem.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await engine.refresh()
    return row


@app.put("/api/elements/{elem_id}")
async def update_element(elem_id: int, elem: ElementIn):
    if not type_store.exists(elem.type):
        raise HTTPException(400, f"type {elem.type!r} is not defined (see Settings)")
    try:
        row = element_store.update(elem_id, elem.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "element not found")
    await engine.refresh()
    return row


@app.delete("/api/elements/{elem_id}")
async def delete_element(elem_id: int):
    in_use = store.count_by_element(elem_id)
    if in_use:
        raise HTTPException(400, f"the element is assigned to {in_use} mimic segment(s)")
    if not element_store.delete(elem_id):
        raise HTTPException(404, "element not found")
    await engine.refresh()
    return {"ok": True}


# ---------- strips (Settings) ----------

@app.get("/api/strips")
def list_strips():
    rows = []
    pwm_idx = 0
    for s in strip_store.list():
        row = dict(s)
        row["hw_led_count"] = manager.hw_count(s["id"])
        row["used_by"] = store.count_by_strip(s["id"])
        if s["kind"] == "pwm":
            hw = cfg["strips"][pwm_idx]
            row.update(gpio=hw["gpio"], channel=hw["channel"], count=hw["count"])
            pwm_idx += 1
        rows.append(row)
    return {"strips": rows, "wled_default_port": WLED_DEFAULT_PORT}


@app.post("/api/strips")
async def add_strip(s: WledStripIn):
    try:
        row = strip_store.add_wled(s.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    manager.sync()
    await engine.refresh()
    return row


@app.put("/api/strips/{strip_id}")
async def update_strip(strip_id: int, s: StripUpdate):
    try:
        row = strip_store.update(strip_id, s.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "strip not found")
    manager.sync()
    await engine.refresh()
    return row


@app.delete("/api/strips/{strip_id}")
async def delete_strip(strip_id: int):
    in_use = store.count_by_strip(strip_id)
    if in_use:
        raise HTTPException(400, f"the strip has {in_use} segment(s) assigned in the mimic")
    try:
        if not strip_store.delete(strip_id):
            raise HTTPException(404, "strip not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    manager.sync()
    engine.pixels.pop(strip_id, None)
    await engine.refresh()
    return {"ok": True}


# ---------- types (Settings) ----------

@app.get("/api/types")
def list_types():
    rows = []
    for t in type_store.list():
        row = dict(t)
        row["used_by"] = element_store.count_by_type(t["name"])
        rows.append(row)
    return {"types": rows, "rules": RULES}


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
        raise HTTPException(404, "type not found")
    if row["name"] != name:
        element_store.rename_type(name, row["name"])
    await engine.refresh()
    return row


@app.delete("/api/types/{name}")
async def delete_type(name: str):
    in_use = element_store.count_by_type(name)
    if in_use:
        raise HTTPException(400, f"type {name!r} is used by {in_use} element(s)")
    if not type_store.delete(name):
        raise HTTPException(404, "type not found")
    return {"ok": True}


# ---------- control ----------

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


@app.post("/api/test-led/{strip}/{led}")
def toggle_test_led(strip: int, led: int):
    """Toggle a single LED blue to verify physical positions."""
    if not engine.test_mode:
        raise HTTPException(400, "enable test mode first")
    _check_strip(strip)
    if not 1 <= led <= engine.display_count(strip):
        raise HTTPException(400, f"LED out of range (1-{engine.display_count(strip)})")
    engine.toggle_test_led(strip, led)
    return {"test_leds": sorted(engine.test_leds)}


@app.post("/api/modbus/write")
async def modbus_write(req: RegisterWrite):
    """Write a register directly (for testing / simulating PLC states)."""
    host = req.host or cfg["modbus"]["host"]
    port = req.port or cfg["modbus"]["port"]
    unit = req.unit or cfg["modbus"]["unit"]
    try:
        await modbus.write_register(host, port, unit, req.address, req.value)
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
            await ws.receive_text()  # just keep the connection alive
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


@app.get("/elements")
def elements_page():
    return FileResponse(web_dir / "elements.html")


@app.get("/settings")
def settings_page():
    return FileResponse(web_dir / "settings.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=cfg["http_port"], log_level="info")
