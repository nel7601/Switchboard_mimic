"""Switchboard Mimic — API REST + WebSocket + frontend estático.

Arranque:  .venv/bin/python -m switchboard.main   (o via systemd)
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
from .leds import create_bank
from .modbus_client import ModbusPool
from .store import SegmentStore
from .typestore import RULES, TypeStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("switchboard")

cfg = load_config()
store = SegmentStore(PROJECT_ROOT / cfg["data_file"])
type_store = TypeStore(PROJECT_ROOT / cfg["data_file"].replace("segments", "types"))
element_store = ElementStore(PROJECT_ROOT / cfg["data_file"].replace("segments", "elements"))
bank = create_bank(cfg["strips"])
modbus = ModbusPool(cfg["modbus"]["timeout_s"])
engine = MimicEngine(
    store, element_store, type_store, bank, modbus,
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
        "Motor del mímico arrancado (%s)",
        ", ".join(f"tira {i+1}: {c} LEDs" for i, c in enumerate(bank.counts)),
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


class RegisterWrite(BaseModel):
    address: int
    value: int
    host: Optional[str] = None
    port: Optional[int] = None
    unit: Optional[int] = None


# ---------- estado ----------

@app.get("/api/state")
def get_state():
    return engine.state()


# ---------- segmentos (vista Mímico) ----------

@app.get("/api/segments")
def list_segments():
    return {"segments": store.list(), "elements": element_store.list()}


def _check_element(elem_id: int):
    if element_store.get(elem_id) is None:
        raise HTTPException(400, f"el elemento id={elem_id} no está definido (ver Elementos)")


def _check_strip(strip: int):
    if not 1 <= strip <= engine.strip_count:
        raise HTTPException(400, f"tira fuera de rango (1-{engine.strip_count})")


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
async def clear_segments(strip: Optional[int] = None):
    """Vacía la tabla completa, o solo la de una tira si se pasa ?strip=N."""
    if strip is not None:
        _check_strip(strip)
    store.clear(strip)
    engine.selected_id = None
    await engine.refresh()
    return {"ok": True}


# ---------- elementos ----------

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
        raise HTTPException(400, f"el tipo {elem.type!r} no está definido (ver Settings)")
    try:
        row = element_store.add(elem.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await engine.refresh()
    return row


@app.put("/api/elements/{elem_id}")
async def update_element(elem_id: int, elem: ElementIn):
    if not type_store.exists(elem.type):
        raise HTTPException(400, f"el tipo {elem.type!r} no está definido (ver Settings)")
    try:
        row = element_store.update(elem_id, elem.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "elemento no encontrado")
    await engine.refresh()
    return row


@app.delete("/api/elements/{elem_id}")
async def delete_element(elem_id: int):
    in_use = store.count_by_element(elem_id)
    if in_use:
        raise HTTPException(400, f"el elemento está asignado a {in_use} segmento(s) del mímico")
    if not element_store.delete(elem_id):
        raise HTTPException(404, "elemento no encontrado")
    await engine.refresh()
    return {"ok": True}


# ---------- tipos (Settings) ----------

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
        raise HTTPException(404, "tipo no encontrado")
    if row["name"] != name:
        element_store.rename_type(name, row["name"])
    await engine.refresh()
    return row


@app.delete("/api/types/{name}")
async def delete_type(name: str):
    in_use = element_store.count_by_type(name)
    if in_use:
        raise HTTPException(400, f"el tipo {name!r} lo usan {in_use} elemento(s)")
    if not type_store.delete(name):
        raise HTTPException(404, "tipo no encontrado")
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
    """Enciende/apaga en azul un LED individual para probar posiciones físicas."""
    if not engine.test_mode:
        raise HTTPException(400, "activa el modo test primero")
    _check_strip(strip)
    if not 1 <= led <= engine.display_count(strip):
        raise HTTPException(400, f"LED fuera de rango (1-{engine.display_count(strip)})")
    engine.toggle_test_led(strip, led)
    return {"test_leds": sorted(engine.test_leds)}


@app.post("/api/modbus/write")
async def modbus_write(req: RegisterWrite):
    """Escritura directa de un registro (para pruebas / simulación de estados del PLC)."""
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


@app.get("/elements")
def elements_page():
    return FileResponse(web_dir / "elements.html")


@app.get("/settings")
def settings_page():
    return FileResponse(web_dir / "settings.html")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=cfg["http_port"], log_level="info")
