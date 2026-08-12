"""Configuration loading from config.json (project root)."""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

DEFAULT_STRIP = {"count": 60, "gpio": 12, "brightness": 50, "channel": 0}

DEFAULTS = {
    "strips": [dict(DEFAULT_STRIP)],
    "modbus": {
        "host": "127.0.0.1",
        "port": 5020,
        "unit": 1,
        "registers_per_element": 5,
        "timeout_s": 1.0,
    },
    "poll_interval_s": 2.0,
    "http_port": 8085,
    "data_file": "data/segments.json",
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if CONFIG_FILE.exists():
        user = json.loads(CONFIG_FILE.read_text())
        for key, value in user.items():
            if key == "led":
                continue  # legacy format, handled below
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
        # backward compatibility with the legacy single-strip format ("led": {...})
        if "strips" not in user and "led" in user:
            strip = dict(DEFAULT_STRIP)
            strip.update(user["led"])
            cfg["strips"] = [strip]
    # normalize every strip against the defaults
    strips = []
    for s in cfg["strips"][:2]:  # rpi_ws281x supports at most 2 PWM channels
        full = dict(DEFAULT_STRIP)
        full.update(s)
        strips.append(full)
    cfg["strips"] = strips
    return cfg
