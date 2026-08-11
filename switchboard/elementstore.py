"""Elementos del mímico: instancias con nombre (Mimic A, Main B, Tie, ...).

Cada elemento tiene un tipo (definido en Settings) y sus parámetros Modbus:
host (IP), puerto, unit/device ID y dirección del primer registro. Los
elementos cuyo tipo usa la regla 'derived' no necesitan parámetros Modbus.
"""
import json
import threading
from pathlib import Path
from typing import Optional


class ElementStore:
    def __init__(self, data_file: Path):
        self._file = data_file
        self._lock = threading.Lock()
        self._elements: list[dict] = []
        self._last_id = 0
        self._load()

    def _load(self):
        if self._file.exists():
            data = json.loads(self._file.read_text())
            self._elements = data.get("elements", [])
            self._last_id = data.get(
                "last_id", max((e["id"] for e in self._elements), default=0)
            )

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_id": self._last_id, "elements": self._elements}
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._file)

    @staticmethod
    def _validate(row: dict) -> dict:
        name = str(row.get("name", "")).strip()
        if not name:
            raise ValueError("el elemento necesita un nombre")
        seg_type = str(row.get("type", "")).strip()
        if not seg_type:
            raise ValueError("el elemento necesita un tipo")
        modbus = row.get("modbus") or {}
        return {
            "name": name,
            "type": seg_type,
            "modbus": {
                "host": str(modbus.get("host", "127.0.0.1")).strip(),
                "port": int(modbus.get("port", 502)),
                "unit": int(modbus.get("unit", 1)),
                "address": int(modbus.get("address", 0)),
            },
        }

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._elements]

    def get(self, elem_id: int) -> Optional[dict]:
        with self._lock:
            return next((dict(e) for e in self._elements if e["id"] == elem_id), None)

    def add(self, row: dict) -> dict:
        clean = self._validate(row)
        with self._lock:
            if any(e["name"] == clean["name"] for e in self._elements):
                raise ValueError(f"ya existe un elemento llamado {clean['name']!r}")
            self._last_id += 1
            clean["id"] = self._last_id
            self._elements.append(clean)
            self._save()
            return dict(clean)

    def update(self, elem_id: int, row: dict) -> Optional[dict]:
        clean = self._validate(row)
        with self._lock:
            for i, e in enumerate(self._elements):
                if e["id"] == elem_id:
                    if clean["name"] != e["name"] and any(
                        o["name"] == clean["name"] for o in self._elements
                    ):
                        raise ValueError(f"ya existe un elemento llamado {clean['name']!r}")
                    clean["id"] = elem_id
                    self._elements[i] = clean
                    self._save()
                    return dict(clean)
            return None

    def delete(self, elem_id: int) -> bool:
        with self._lock:
            before = len(self._elements)
            self._elements = [e for e in self._elements if e["id"] != elem_id]
            if len(self._elements) != before:
                self._save()
                return True
            return False

    def count_by_type(self, type_name: str) -> int:
        with self._lock:
            return sum(1 for e in self._elements if e["type"] == type_name)

    def rename_type(self, old: str, new: str) -> int:
        with self._lock:
            n = 0
            for e in self._elements:
                if e["type"] == old:
                    e["type"] = new
                    n += 1
            if n:
                self._save()
            return n
