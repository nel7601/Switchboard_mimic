"""Carga de configuración desde config.json (raíz del proyecto)."""
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

DEFAULTS = {
    "led": {"count": 60, "gpio": 12, "brightness": 50, "channel": 0},
    "modbus": {
        "host": "127.0.0.1",
        "port": 5020,
        "unit": 1,
        "registers_per_element": 5,
        "timeout_s": 1.0,
    },
    "poll_interval_s": 2.0,
    "http_port": 8080,
    "data_file": "data/segments.json",
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if CONFIG_FILE.exists():
        user = json.loads(CONFIG_FILE.read_text())
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg
