"""System LED strips, persisted and user-definable.

Two kinds of strip:
  pwm  : the Raspberry Pi's local strips (max. 2, PWM channels). They come from
         config.json and are fixed: only their name can be changed from the UI.
  wled : ESP32 controllers running WLED, reachable over the network. Created,
         edited and deleted from Settings with name, host, port and LED count.
"""
import json
import threading
from pathlib import Path
from typing import Optional

WLED_DEFAULT_PORT = 21324  # WLED's default realtime UDP port


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
        # make sure the pwm entries exist (first start or config change)
        pwm_entries = [s for s in self._strips if s["kind"] == "pwm"]
        if len(pwm_entries) != self._pwm_count:
            others = [s for s in self._strips if s["kind"] != "pwm"]
            pwm_entries = [
                {"id": i + 1, "name": f"Strip {i + 1}", "kind": "pwm"}
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
            raise ValueError("the strip needs a name")
        host = str(row.get("host", "")).strip()
        if not host:
            raise ValueError("a WLED strip needs the controller's host/IP")
        port = int(row.get("port", WLED_DEFAULT_PORT))
        count = int(row.get("count", 60))
        if count < 1:
            raise ValueError("LED count must be >= 1")
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
                raise ValueError(f"a strip named {clean['name']!r} already exists")
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
                    raise ValueError("the strip needs a name")
                if name != s["name"] and any(
                    o["name"] == name for o in self._strips
                ):
                    raise ValueError(f"a strip named {name!r} already exists")
                if s["kind"] == "pwm":
                    # local strips only allow a name change
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
                raise ValueError("local PWM strips cannot be deleted")
            self._strips = [s for s in self._strips if s["id"] != strip_id]
            self._save()
            return True
