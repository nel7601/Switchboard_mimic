"""Ciclo de refresco del mímico (port del flujo 'Print' de Node-RED).

Modo RUN : resuelve cada segmento a su elemento, lee Modbus con los parámetros
           del elemento, calcula color y pinta la tira.
Modo TEST: congela el refresco y resalta en azul el segmento seleccionado.
"""
import asyncio
import logging
from typing import Callable, Optional

from .colors import COLOR_RGB, color_from_registers, derived_color
from .elementstore import ElementStore
from .leds import BaseStrip
from .modbus_client import ModbusPool
from .store import SegmentStore
from .typestore import TypeStore

log = logging.getLogger(__name__)


class MimicEngine:
    def __init__(
        self,
        store: SegmentStore,
        elements: ElementStore,
        types: TypeStore,
        strip: BaseStrip,
        modbus: ModbusPool,
        registers_per_element: int = 5,
        poll_interval_s: float = 2.0,
    ):
        self.store = store
        self.elements = elements
        self.types = types
        self.strip = strip
        self.modbus = modbus
        self._reg_count = registers_per_element
        self._interval = poll_interval_s
        self.test_mode = False
        self.selected_id: Optional[int] = None
        self.test_leds: set = set()  # LEDs encendidos a mano en modo test (base 1)
        self.pixels: list = [(0, 0, 0)] * strip.count  # buffer virtual (puede exceder la tira)
        self.resolved: list[dict] = []  # última tabla con colores
        self.modbus_ok: Optional[bool] = None
        self.on_update: Optional[Callable] = None  # callback para el websocket
        self._task: Optional[asyncio.Task] = None
        self._refresh_lock: Optional[asyncio.Lock] = None  # perezoso (Python 3.9)

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
        """Una pasada completa: resolver color de cada segmento y pintar la tira.

        Serializada: el poller y las llamadas de la API no se interfieren."""
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        async with self._refresh_lock:
            await self._refresh_inner()

    async def _refresh_inner(self):
        resolved = []
        ok = True
        for seg in self.store.list():
            row = dict(seg)
            elem = self.elements.get(seg["element_id"])
            if elem is None:
                row.update(element="?", type="?", rule="simple", color="Gray")
                resolved.append(row)
                continue
            row["element"] = elem["name"]
            row["type"] = elem["type"]
            row["rule"] = self.types.rule_for(elem["type"])
            try:
                if row["rule"] == "derived":
                    row["color"] = derived_color(resolved, seg["start"])
                else:
                    mb = elem["modbus"]
                    regs = await self.modbus.read_holding(
                        mb["host"], mb["port"], mb["unit"], mb["address"], self._reg_count
                    )
                    row["color"] = color_from_registers(row["rule"], regs)
            except Exception as exc:
                log.warning("Segmento %s (%s): %s", seg["id"], elem["name"], exc)
                row["color"] = "Gray"
                ok = False
            resolved.append(row)

        self.resolved = resolved
        self.modbus_ok = ok
        self._paint()
        self._notify()

    # ---------- pintado ----------

    def display_count(self) -> int:
        """LEDs a mostrar: al menos la tira física, y crece si la tabla asigna más."""
        count = self.strip.count
        for seg in self.store.list():
            count = max(count, seg["start"], seg["end"])
        count = max(count, *self.test_leds) if self.test_leds else count
        return count

    def _paint(self):
        """Pinta el buffer virtual completo; la tira física recibe solo lo que le cabe."""
        n = self.display_count()
        pixels = [(0, 0, 0)] * n
        for row in self.resolved:
            rgb = COLOR_RGB.get(row["color"], COLOR_RGB["Gray"])
            lo, hi = min(row["start"], row["end"]), max(row["start"], row["end"])
            for led in range(lo, hi + 1):
                if 1 <= led <= n:
                    pixels[led - 1] = rgb
        if self.test_mode:
            if self.selected_id is not None:
                sel = self.store.get(self.selected_id)
                if sel:
                    lo, hi = min(sel["start"], sel["end"]), max(sel["start"], sel["end"])
                    for led in range(lo, hi + 1):
                        if 1 <= led <= n:
                            pixels[led - 1] = COLOR_RGB["Blue"]
            for led in self.test_leds:
                if 1 <= led <= n:
                    pixels[led - 1] = COLOR_RGB["Blue"]
        self.pixels = pixels
        self.strip.render(pixels)

    # ---------- interacción desde la API ----------

    def set_test_mode(self, enabled: bool):
        self.test_mode = enabled
        if not enabled:
            self.selected_id = None
            self.test_leds.clear()
        self._paint()
        self._notify()

    def toggle_test_led(self, led: int):
        """Enciende/apaga en azul un LED individual (solo en modo test)."""
        if led in self.test_leds:
            self.test_leds.discard(led)
        else:
            self.test_leds.add(led)
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
            "test_leds": sorted(self.test_leds),
            "modbus_ok": self.modbus_ok,
            "segments": self.resolved,
            "pixels": self.pixels,
            "led_count": len(self.pixels),
            "hw_led_count": self.strip.count,
        }

    def _notify(self):
        if self.on_update:
            self.on_update(self.state())
