"""Persistencia de la tabla de segmentos (equivale a tableAData + persist de Node-RED)."""
import json
import threading
from pathlib import Path
from typing import Optional

class SegmentStore:
    """Tabla de segmentos: cada fila mapea un tramo de LEDs a un elemento eléctrico.

    Campos: id, start, end (LEDs, base 1), description, type, station (dirección Modbus).
    """

    def __init__(self, data_file: Path):
        self._file = data_file
        self._lock = threading.Lock()
        self._segments: list[dict] = []
        self._last_id = 0
        self._load()

    def _load(self):
        if self._file.exists():
            data = json.loads(self._file.read_text())
            self._segments = data.get("segments", [])
            self._last_id = data.get("last_id", max((s["id"] for s in self._segments), default=0))

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_id": self._last_id, "segments": self._segments}
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._file)

    @staticmethod
    def _validate(row: dict) -> dict:
        seg_type = str(row.get("type", "")).strip()
        if not seg_type:
            raise ValueError("el segmento necesita un tipo")
        start, end = int(row.get("start", 1)), int(row.get("end", 1))
        if start < 1 or end < 1:
            raise ValueError("start/end deben ser >= 1")
        return {
            "start": start,
            "end": end,
            "description": str(row.get("description", "")),
            "type": seg_type,
            "station": int(row.get("station", 0)),
        }

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._segments]

    def get(self, seg_id: int) -> Optional[dict]:
        with self._lock:
            return next((dict(s) for s in self._segments if s["id"] == seg_id), None)

    def add(self, row: dict) -> dict:
        clean = self._validate(row)
        with self._lock:
            self._last_id += 1
            clean["id"] = self._last_id
            self._segments.append(clean)
            self._save()
            return dict(clean)

    def update(self, seg_id: int, row: dict) -> Optional[dict]:
        clean = self._validate(row)
        with self._lock:
            for i, seg in enumerate(self._segments):
                if seg["id"] == seg_id:
                    clean["id"] = seg_id
                    self._segments[i] = clean
                    self._save()
                    return dict(clean)
            return None

    def delete(self, seg_id: int) -> bool:
        with self._lock:
            before = len(self._segments)
            self._segments = [s for s in self._segments if s["id"] != seg_id]
            if len(self._segments) != before:
                self._save()
                return True
            return False

    def clear(self):
        with self._lock:
            self._segments = []
            self._last_id = 0
            self._save()

    def count_by_type(self, type_name: str) -> int:
        with self._lock:
            return sum(1 for s in self._segments if s["type"] == type_name)

    def rename_type(self, old: str, new: str) -> int:
        """Cascada al renombrar un tipo en Settings. Devuelve filas afectadas."""
        with self._lock:
            n = 0
            for seg in self._segments:
                if seg["type"] == old:
                    seg["type"] = new
                    n += 1
            if n:
                self._save()
            return n
