"""Tiras LED del sistema, persistidas y definibles por el usuario.

Dos clases de tira:
  pwm  : las tiras locales de la Raspberry Pi (máx. 2, canales PWM). Vienen del
         config.json y son fijas: solo se les puede cambiar el nombre desde la UI.
  wled : controladores ESP32 con WLED accesibles por red. Se crean/editan/borran
         desde Settings con nombre, host, puerto y nº de LEDs.
"""
import json
import threading
from pathlib import Path
from typing import Optional

WLED_DEFAULT_PORT = 21324  # puerto UDP realtime por defecto de WLED


class StripStore:
    def __init__(self, data_file: Path, pwm_cfg: list):
        self._file = data_file
        self._lock = threading.Lock()
        self._strips: list[dict] = []
        self._last_id = 0
        self._pwm_count = len(pwm_cfg)
        self._load(pwm_cfg)

    def _load(self, pwm_cfg: list):
        if self._file.exists():
            data = json.loads(self._file.read_text())
            self._strips = data.get("strips", [])
            self._last_id = data.get(
                "last_id", max((s["id"] for s in self._strips), default=0)
            )
        # garantizar que existen las entradas pwm (primer arranque o cambio de config)
        pwm_entries = [s for s in self._strips if s["kind"] == "pwm"]
        if len(pwm_entries) != self._pwm_count:
            others = [s for s in self._strips if s["kind"] != "pwm"]
            pwm_entries = [
                {"id": i + 1, "name": f"Tira {i + 1}", "kind": "pwm"}
                for i in range(self._pwm_count)
            ]
            self._strips = pwm_entries + others
            self._last_id = max(self._last_id, self._pwm_count)
            self._save()

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_id": self._last_id, "strips": self._strips}
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._file)

    @staticmethod
    def _validate_wled(row: dict) -> dict:
        name = str(row.get("name", "")).strip()
        if not name:
            raise ValueError("la tira necesita un nombre")
        host = str(row.get("host", "")).strip()
        if not host:
            raise ValueError("la tira WLED necesita el host/IP del controlador")
        port = int(row.get("port", WLED_DEFAULT_PORT))
        count = int(row.get("count", 60))
        if count < 1:
            raise ValueError("el nº de LEDs debe ser >= 1")
        return {"name": name, "kind": "wled", "host": host, "port": port, "count": count}

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._strips]

    def get(self, strip_id: int) -> Optional[dict]:
        with self._lock:
            return next((dict(s) for s in self._strips if s["id"] == strip_id), None)

    def exists(self, strip_id: int) -> bool:
        return self.get(strip_id) is not None

    def add_wled(self, row: dict) -> dict:
        clean = self._validate_wled(row)
        with self._lock:
            if any(s["name"] == clean["name"] for s in self._strips):
                raise ValueError(f"ya existe una tira llamada {clean['name']!r}")
            self._last_id += 1
            clean["id"] = self._last_id
            self._strips.append(clean)
            self._save()
            return dict(clean)

    def update(self, strip_id: int, row: dict) -> Optional[dict]:
        with self._lock:
            for i, s in enumerate(self._strips):
                if s["id"] != strip_id:
                    continue
                name = str(row.get("name", s["name"])).strip()
                if not name:
                    raise ValueError("la tira necesita un nombre")
                if name != s["name"] and any(
                    o["name"] == name for o in self._strips
                ):
                    raise ValueError(f"ya existe una tira llamada {name!r}")
                if s["kind"] == "pwm":
                    # de las tiras locales solo se puede cambiar el nombre
                    self._strips[i] = {**s, "name": name}
                else:
                    clean = self._validate_wled({**s, **row, "name": name})
                    clean["id"] = strip_id
                    self._strips[i] = clean
                self._save()
                return dict(self._strips[i])
            return None

    def delete(self, strip_id: int) -> bool:
        with self._lock:
            target = next((s for s in self._strips if s["id"] == strip_id), None)
            if target is None:
                return False
            if target["kind"] == "pwm":
                raise ValueError("las tiras PWM locales no se pueden borrar")
            self._strips = [s for s in self._strips if s["id"] != strip_id]
            self._save()
            return True
