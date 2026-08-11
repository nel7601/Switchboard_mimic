"""Ciclo de refresco del mímico (port del flujo 'Print' de Node-RED).

Modo RUN : lee Modbus por cada segmento, calcula color y pinta la tira.
Modo TEST: congela el refresco y resalta en azul el segmento seleccionado
           (equivale al switch 'Testing position' + selección de fila).
"""
import asyncio
import logging
from typing import Callable, Optional

from .colors import COLOR_RGB, color_from_registers, feeder_color
from .leds import BaseStrip
from .modbus_client import ModbusReader
from .store import SegmentStore

log = logging.getLogger(__name__)


class MimicEngine:
    def __init__(
        self,
        store: SegmentStore,
        strip: BaseStrip,
        modbus: ModbusReader,
        registers_per_element: int = 5,
        poll_interval_s: float = 2.0,
    ):
        self.store = store
        self.strip = strip
        self.modbus = modbus
        self._reg_count = registers_per_element
        self._interval = poll_interval_s
        self.test_mode = False
        self.selected_id: Optional[int] = None
        self.resolved: list[dict] = []  # última tabla con colores (extTableAData)
        self.modbus_ok: Optional[bool] = None
        self.on_update: Optional[Callable] = None  # callback para el websocket
        self._task: Optional[asyncio.Task] = None

    # ---------- ciclo principal ----------

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
        self.strip.clear()
        await self.modbus.close()

    async def _loop(self):
        while True:
            try:
                if not self.test_mode:
                    await self.refresh()
            except Exception:
                log.exception("Fallo en el ciclo de refresco")
            await asyncio.sleep(self._interval)

    async def refresh(self):
        """Una pasada completa: resolver color de cada segmento y pintar la tira."""
        resolved = []
        ok = True
        for seg in self.store.list():
            row = dict(seg)
            try:
                if seg["type"] == "Feeder":
                    row["color"] = feeder_color(resolved, seg["start"])
                else:
                    regs = await self.modbus.read_holding(seg["station"], self._reg_count)
                    row["color"] = color_from_registers(seg["type"], regs)
            except Exception as exc:
                log.warning("Segmento %s (addr %s): %s", seg["id"], seg["station"], exc)
                row["color"] = "Gray"
                ok = False
            resolved.append(row)

        self.resolved = resolved
        self.modbus_ok = ok
        self._paint()
        self._notify()

    # ---------- pintado ----------

    def _paint(self):
        pixels = [(0, 0, 0)] * self.strip.count
        for row in self.resolved:
            rgb = COLOR_RGB.get(row["color"], COLOR_RGB["Gray"])
            lo, hi = min(row["start"], row["end"]), max(row["start"], row["end"])
            for led in range(lo, hi + 1):
                if 1 <= led <= self.strip.count:
                    pixels[led - 1] = rgb
        if self.test_mode and self.selected_id is not None:
            sel = self.store.get(self.selected_id)
            if sel:
                lo, hi = min(sel["start"], sel["end"]), max(sel["start"], sel["end"])
                for led in range(lo, hi + 1):
                    if 1 <= led <= self.strip.count:
                        pixels[led - 1] = COLOR_RGB["Blue"]
        self.strip.render(pixels)

    # ---------- interacción desde la API ----------

    def set_test_mode(self, enabled: bool):
        self.test_mode = enabled
        if not enabled:
            self.selected_id = None
        self._paint()
        self._notify()

    def select_segment(self, seg_id: Optional[int]):
        self.selected_id = seg_id
        self._paint()
        self._notify()

    def state(self) -> dict:
        return {
            "test_mode": self.test_mode,
            "selected_id": self.selected_id,
            "modbus_ok": self.modbus_ok,
            "segments": self.resolved,
            "pixels": self.strip.pixels,
            "led_count": self.strip.count,
        }

    def _notify(self):
        if self.on_update:
            self.on_update(self.state())
