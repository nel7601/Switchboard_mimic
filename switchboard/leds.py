"""Driver de la tira WS2812B con fallback a mock cuando no hay hardware/root.

La interfaz es un buffer completo: render(pixels) recibe la lista entera de RGB.
"""
import logging

log = logging.getLogger(__name__)


class BaseStrip:
    def __init__(self, count: int):
        self.count = count
        self.pixels = [(0, 0, 0)] * count

    def render(self, pixels: list):
        self.pixels = [
            pixels[i] if i < len(pixels) else (0, 0, 0) for i in range(self.count)
        ]
        self._show()

    def clear(self):
        self.render([(0, 0, 0)] * self.count)

    def _show(self):
        raise NotImplementedError


class MockStrip(BaseStrip):
    """Sin hardware: el estado queda en memoria y se sirve al preview web."""

    def _show(self):
        pass


class Ws281xStrip(BaseStrip):
    def __init__(self, count: int, gpio: int = 12, brightness: int = 50, channel: int = 0):
        super().__init__(count)
        from rpi_ws281x import PixelStrip, Color

        self._Color = Color
        # frecuencia 800kHz, DMA 10 — mismos valores que neopix.py de node-red-node-pi-neopixel
        self._strip = PixelStrip(count, gpio, 800000, 10, False, brightness, channel)
        self._strip.begin()

    def _show(self):
        for i, (r, g, b) in enumerate(self.pixels):
            self._strip.setPixelColor(i, self._Color(r, g, b))
        self._strip.show()


def create_strip(cfg: dict) -> BaseStrip:
    count = cfg["count"]
    try:
        strip = Ws281xStrip(count, cfg["gpio"], cfg["brightness"], cfg.get("channel", 0))
        log.info("Tira WS2812B inicializada: %d LEDs en GPIO%d", count, cfg["gpio"])
        return strip
    except Exception as exc:
        log.warning("Sin acceso al hardware LED (%s) — usando driver simulado", exc)
        return MockStrip(count)
