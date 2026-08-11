"""Persistencia de la tabla de asignación del mímico.

Cada fila asocia un tramo de LEDs (`start`–`end`, base 1) de una tira (`strip`,
base 1) a un elemento definido en la vista de Elementos (`element_id`).
"""
import json
import threading
from pathlib import Path
from typing import Optional


class SegmentStore:
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
            for seg in self._segments:
                seg.setdefault("strip", 1)  # datos anteriores a multi-tira
            self._last_id = data.get("last_id", max((s["id"] for s in self._segments), default=0))

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_id": self._last_id, "segments": self._segments}
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._file)

    @staticmethod
    def _validate(row: dict) -> dict:
        start, end = int(row.get("start", 1)), int(row.get("end", 1))
        if start < 1 or end < 1:
            raise ValueError("start/end deben ser >= 1")
        strip = int(row.get("strip", 1))
        if strip < 1:
            raise ValueError("strip debe ser >= 1")
        element_id = int(row.get("element_id", 0))
        if element_id < 1:
            raise ValueError("el segmento necesita un elemento asociado")
        return {"strip": strip, "start": start, "end": end, "element_id": element_id}

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._segments]

    def get(self, seg_id: int) -> Optional[dict]:
        with self._lock:
            return next((dict(s) for s in self._segments if s["id"] == seg_id), None)

    def _find_overlap(self, clean: dict, exclude_id: Optional[int] = None) -> Optional[dict]:
        """Devuelve el segmento existente que solapa con el rango dado, si lo hay.
        Debe llamarse con el lock tomado."""
        lo, hi = min(clean["start"], clean["end"]), max(clean["start"], clean["end"])
        for seg in self._segments:
            if seg["id"] == exclude_id or seg["strip"] != clean["strip"]:
                continue
            s_lo, s_hi = min(seg["start"], seg["end"]), max(seg["start"], seg["end"])
            if lo <= s_hi and s_lo <= hi:
                return seg
        return None

    def add(self, row: dict) -> dict:
        clean = self._validate(row)
        with self._lock:
            other = self._find_overlap(clean)
            if other:
                raise ValueError(
                    f"los LEDs {clean['start']}-{clean['end']} de la tira {clean['strip']} ya "
                    f"están asignados: solapan con el segmento #{other['id']} "
                    f"(LED {other['start']}-{other['end']})"
                )
            self._last_id += 1
            clean["id"] = self._last_id
            self._segments.append(clean)
            self._save()
            return dict(clean)

    def update(self, seg_id: int, row: dict) -> Optional[dict]:
        clean = self._validate(row)
        with self._lock:
            other = self._find_overlap(clean, exclude_id=seg_id)
            if other:
                raise ValueError(
                    f"los LEDs {clean['start']}-{clean['end']} de la tira {clean['strip']} ya "
                    f"están asignados: solapan con el segmento #{other['id']} "
                    f"(LED {other['start']}-{other['end']})"
                )
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

    def clear(self, strip: Optional[int] = None):
        """Vacía la tabla; con `strip` borra solo los segmentos de esa tira."""
        with self._lock:
            if strip is None:
                self._segments = []
                self._last_id = 0
            else:
                self._segments = [s for s in self._segments if s["strip"] != strip]
            self._save()

    def count_by_element(self, element_id: int) -> int:
        with self._lock:
            return sum(1 for s in self._segments if s["element_id"] == element_id)
