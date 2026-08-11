"""Ciclo de refresco del mímico (port del flujo 'Print' de Node-RED).

Modo RUN : resuelve cada segmento a su elemento, lee Modbus con los parámetros
           del elemento, calcula color y pinta las tiras.
Modo TEST: congela el refresco y resalta en azul el segmento seleccionado o los
           LEDs marcados a mano.
"""
import asyncio
import logging
from typing import Callable, Optional

from .colors import COLOR_RGB, color_from_registers, derived_color
from .elementstore import ElementStore
from .leds import BaseBank
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
        bank: BaseBank,
        modbus: ModbusPool,
        registers_per_element: int = 5,
        poll_interval_s: float = 2.0,
    ):
        self.store = store
        self.elements = elements
        self.types = types
        self.bank = bank
        self.modbus = modbus
        self._reg_count = registers_per_element
        self._interval = poll_interval_s
        self.test_mode = False
        self.selected_id: Optional[int] = None
        self.test_leds: set = set()  # {(tira, led)} encendidos a mano en modo test (base 1)
        # buffers virtuales por tira (pueden exceder la tira física)
        self.pixels: list = [[(0, 0, 0)] * c for c in bank.counts]
        self.resolved: list[dict] = []  # última tabla con colores
        self.modbus_ok: Optional[bool] = None
        self.on_update: Optional[Callable] = None  # callback para el websocket
        self._task: Optional[asyncio.Task] = None
        self._refresh_lock: Optional[asyncio.Lock] = None  # perezoso (Python 3.9)

    @property
    def strip_count(self) -> int:
        return len(self.bank.counts)

    # ---------- ciclo principal ----------

    async def start(self):
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
        self.bank.clear()
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
        """Una pasada completa: resolver color de cada segmento y pintar las tiras.

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

    def display_count(self, strip: int) -> int:
        """LEDs a mostrar en la tira `strip` (base 1): al menos la tira física,
        y crece si la tabla asigna más."""
        count = self.bank.counts[strip - 1]
        for seg in self.store.list():
            if seg["strip"] == strip:
                count = max(count, seg["start"], seg["end"])
        for s, led in self.test_leds:
            if s == strip:
                count = max(count, led)
        return count

    def _paint(self):
        """Pinta los buffers virtuales; cada tira física recibe solo lo que le cabe."""
        buffers = [
            [(0, 0, 0)] * self.display_count(strip)
            for strip in range(1, self.strip_count + 1)
        ]
        for row in self.resolved:
            if not 1 <= row["strip"] <= self.strip_count:
                continue
            buf = buffers[row["strip"] - 1]
            rgb = COLOR_RGB.get(row["color"], COLOR_RGB["Gray"])
            lo, hi = min(row["start"], row["end"]), max(row["start"], row["end"])
            for led in range(lo, hi + 1):
                if 1 <= led <= len(buf):
                    buf[led - 1] = rgb
        if self.test_mode:
            if self.selected_id is not None:
                sel = self.store.get(self.selected_id)
                if sel and 1 <= sel["strip"] <= self.strip_count:
                    buf = buffers[sel["strip"] - 1]
                    lo, hi = min(sel["start"], sel["end"]), max(sel["start"], sel["end"])
                    for led in range(lo, hi + 1):
                        if 1 <= led <= len(buf):
                            buf[led - 1] = COLOR_RGB["Blue"]
            for s, led in self.test_leds:
                if 1 <= s <= self.strip_count and 1 <= led <= len(buffers[s - 1]):
                    buffers[s - 1][led - 1] = COLOR_RGB["Blue"]
        self.pixels = buffers
        for idx, buf in enumerate(buffers):
            self.bank.render(idx, buf)

    # ---------- interacción desde la API ----------

    def set_test_mode(self, enabled: bool):
        self.test_mode = enabled
        if not enabled:
            self.selected_id = None
            self.test_leds.clear()
        self._paint()
        self._notify()

    def toggle_test_led(self, strip: int, led: int):
        """Enciende/apaga en azul un LED individual de una tira (solo en modo test)."""
        key = (strip, led)
        if key in self.test_leds:
            self.test_leds.discard(key)
        else:
            self.test_leds.add(key)
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
            "strips": [
                {
                    "pixels": self.pixels[i],
                    "led_count": len(self.pixels[i]),
                    "hw_led_count": self.bank.counts[i],
                }
                for i in range(self.strip_count)
            ],
        }

    def _notify(self):
        if self.on_update:
            self.on_update(self.state())
