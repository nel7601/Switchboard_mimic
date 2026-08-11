"""Banco de tiras WS2812B con fallback a mock cuando no hay hardware/root.

Soporta 1 o 2 tiras. PWM0 (GPIO 12/18) y PWM1 (GPIO 13/19) comparten el
periférico PWM y el canal DMA, así que ambas se manejan desde una única
inicialización ws2811 usando la API de bajo nivel de rpi_ws281x.

Interfaz del banco:
  counts        -> lista con el nº de LEDs de cada tira
  pixels        -> lista de buffers [(r,g,b), ...] por tira (estado actual)
  render(idx, pixels) -> pinta una tira (la lista se recorta/rellena al tamaño)
  clear()       -> apaga todas
"""
import logging

log = logging.getLogger(__name__)

LED_FREQ_HZ = 800000
LED_DMA = 10  # mismo DMA que usaba neopix.py de Node-RED
LED_INVERT = 0


class BaseBank:
    def __init__(self, counts: list):
        self.counts = list(counts)
        self.pixels = [[(0, 0, 0)] * c for c in self.counts]

    def render(self, idx: int, pixels: list):
        count = self.counts[idx]
        self.pixels[idx] = [
            tuple(pixels[i]) if i < len(pixels) else (0, 0, 0) for i in range(count)
        ]
        self._show(idx)

    def clear(self):
        for idx in range(len(self.counts)):
            self.render(idx, [])

    def _show(self, idx: int):
        raise NotImplementedError


class MockBank(BaseBank):
    """Sin hardware: el estado queda en memoria y se sirve al preview web."""

    def _show(self, idx: int):
        pass


class Ws281xBank(BaseBank):
    def __init__(self, strips_cfg: list):
        super().__init__([s["count"] for s in strips_cfg])
        from rpi_ws281x import ws

        self._ws = ws
        self._leds = ws.new_ws2811_t()
        self._channels = []

        # Los dos canales del ws2811 deben configurarse siempre; el que no se
        # usa queda con count=0.
        by_channel = {s["channel"]: s for s in strips_cfg}
        if len(by_channel) != len(strips_cfg):
            raise ValueError("cada tira debe usar un canal PWM distinto (0 y 1)")
        for ch_num in (0, 1):
            channel = ws.ws2811_channel_get(self._leds, ch_num)
            s = by_channel.get(ch_num)
            ws.ws2811_channel_t_count_set(channel, s["count"] if s else 0)
            ws.ws2811_channel_t_gpionum_set(channel, s["gpio"] if s else 0)
            ws.ws2811_channel_t_invert_set(channel, LED_INVERT)
            ws.ws2811_channel_t_brightness_set(channel, s["brightness"] if s else 0)
            ws.ws2811_channel_t_strip_type_set(channel, ws.WS2811_STRIP_GRB)

        ws.ws2811_t_freq_set(self._leds, LED_FREQ_HZ)
        ws.ws2811_t_dmanum_set(self._leds, LED_DMA)

        resp = ws.ws2811_init(self._leds)
        if resp != 0:
            raise RuntimeError(
                f"ws2811_init falló ({resp}): {ws.ws2811_get_return_t_str(resp)}"
            )
        # canal ws de cada tira, en el mismo orden que strips_cfg
        self._channels = [
            ws.ws2811_channel_get(self._leds, s["channel"]) for s in strips_cfg
        ]

    def _show(self, idx: int):
        channel = self._channels[idx]
        for i, (r, g, b) in enumerate(self.pixels[idx]):
            self._ws.ws2811_led_set(channel, i, (r << 16) | (g << 8) | b)
        resp = self._ws.ws2811_render(self._leds)
        if resp != 0:
            log.warning("ws2811_render devolvió %s", resp)


def create_bank(strips_cfg: list) -> BaseBank:
    try:
        bank = Ws281xBank(strips_cfg)
        desc = ", ".join(
            f"tira {i+1}: {s['count']} LEDs GPIO{s['gpio']} (PWM{s['channel']})"
            for i, s in enumerate(strips_cfg)
        )
        log.info("Banco WS2812B inicializado — %s", desc)
        return bank
    except Exception as exc:
        log.warning("Sin acceso al hardware LED (%s) — usando driver simulado", exc)
        return MockBank([s["count"] for s in strips_cfg])
