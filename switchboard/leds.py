"""LED strip drivers.

- Local WS2812B strips (max. 2): PWM0 (GPIO 12/18) and PWM1 (GPIO 13/19) share
  the PWM peripheral and the DMA channel, so both are driven from a single
  ws2811 initialization using the low-level rpi_ws281x API. Falls back to a
  mock when there is no hardware/root access.
- Remote WLED strips (ESP32): WLED's DNRGB realtime UDP protocol, dependency
  free. Fire-and-forget: an unreachable controller never blocks anything.

StripManager unifies both and routes rendering by strip id (StripStore).
"""
import logging
import socket

log = logging.getLogger(__name__)

LED_FREQ_HZ = 800000
LED_DMA = 10  # same DMA channel the Node-RED neopix.py used
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
    """No hardware: state stays in memory and feeds the web preview."""

    def _show(self, idx: int):
        pass


class Ws281xBank(BaseBank):
    def __init__(self, strips_cfg: list):
        super().__init__([s["count"] for s in strips_cfg])
        from rpi_ws281x import ws

        self._ws = ws
        self._leds = ws.new_ws2811_t()
        self._channels = []

        # Both ws2811 channels must always be configured; an unused one is
        # left with count=0.
        by_channel = {s["channel"]: s for s in strips_cfg}
        if len(by_channel) != len(strips_cfg):
            raise ValueError("each strip must use a different PWM channel (0 and 1)")
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
                f"ws2811_init failed ({resp}): {ws.ws2811_get_return_t_str(resp)}"
            )
        # ws channel of each strip, in the same order as strips_cfg
        self._channels = [
            ws.ws2811_channel_get(self._leds, s["channel"]) for s in strips_cfg
        ]

    def _show(self, idx: int):
        channel = self._channels[idx]
        for i, (r, g, b) in enumerate(self.pixels[idx]):
            self._ws.ws2811_led_set(channel, i, (r << 16) | (g << 8) | b)
        resp = self._ws.ws2811_render(self._leds)
        if resp != 0:
            log.warning("ws2811_render returned %s", resp)


def create_bank(strips_cfg: list) -> BaseBank:
    try:
        bank = Ws281xBank(strips_cfg)
        desc = ", ".join(
            f"strip {i+1}: {s['count']} LEDs GPIO{s['gpio']} (PWM{s['channel']})"
            for i, s in enumerate(strips_cfg)
        )
        log.info("WS2812B bank initialized — %s", desc)
        return bank
    except Exception as exc:
        log.warning("No LED hardware access (%s) — using mock driver", exc)
        return MockBank([s["count"] for s in strips_cfg])


class WledSender:
    """Sends the full buffer to a WLED controller over UDP (DNRGB protocol).

    DNRGB: [4, timeout, idx_high, idx_low, r,g,b, r,g,b, ...] — allows chunking
    long strips into several packets (max. 489 LEDs per datagram).
    timeout=255 keeps WLED in realtime mode indefinitely.
    """

    MAX_LEDS_PER_PACKET = 489
    REALTIME_FOREVER = 255

    def __init__(self, host: str, port: int, count: int):
        self.host = host
        self.port = port
        self.count = count
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def render(self, pixels: list):
        buf = [
            tuple(pixels[i]) if i < len(pixels) else (0, 0, 0) for i in range(self.count)
        ]
        try:
            i = 0
            while i < self.count:
                chunk = buf[i : i + self.MAX_LEDS_PER_PACKET]
                data = bytes([4, self.REALTIME_FOREVER, (i >> 8) & 0xFF, i & 0xFF])
                data += b"".join(bytes(p) for p in chunk)
                self._sock.sendto(data, (self.host, self.port))
                i += len(chunk)
        except OSError as exc:
            log.warning("WLED %s:%s unreachable: %s", self.host, self.port, exc)

    def close(self):
        self._sock.close()


class StripManager:
    """Routes rendering by strip id: local PWM strips (single ws2811 bank,
    created at startup) + WLED strips (hot-syncable)."""

    def __init__(self, pwm_cfg: list, strip_store):
        self._store = strip_store
        self._bank = create_bank(pwm_cfg) if pwm_cfg else MockBank([])
        # pwm entries in the store follow the same order as pwm_cfg
        self._pwm_index = {
            e["id"]: i
            for i, e in enumerate(s for s in strip_store.list() if s["kind"] == "pwm")
        }
        self._wled: dict = {}  # id -> WledSender
        self.sync()

    def sync(self):
        """Reconcile WLED senders with the StripStore (adds, removals, changes)."""
        entries = {s["id"]: s for s in self._store.list() if s["kind"] == "wled"}
        for sid in list(self._wled):
            e = entries.get(sid)
            sender = self._wled[sid]
            if e is None or (e["host"], e["port"], e["count"]) != (
                sender.host, sender.port, sender.count
            ):
                sender.close()
                del self._wled[sid]
        for sid, e in entries.items():
            if sid not in self._wled:
                self._wled[sid] = WledSender(e["host"], e["port"], e["count"])

    def ids(self) -> list:
        return [s["id"] for s in self._store.list()]

    def hw_count(self, strip_id: int) -> int:
        if strip_id in self._pwm_index:
            return self._bank.counts[self._pwm_index[strip_id]]
        sender = self._wled.get(strip_id)
        return sender.count if sender else 0

    def render(self, strip_id: int, pixels: list):
        if strip_id in self._pwm_index:
            self._bank.render(self._pwm_index[strip_id], pixels)
        elif strip_id in self._wled:
            self._wled[strip_id].render(pixels)

    def clear(self):
        self._bank.clear()
        for sender in self._wled.values():
            sender.render([])
