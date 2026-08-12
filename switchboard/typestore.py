"""Object types assignable to segments, user-definable.

Each type carries a color rule:
  simple  : reg[0]=1 -> Red, otherwise Green
  breaker : reg[2]=1 -> Yellow (tripped), reg[1]=1 -> Red,
            reg[0]=1 -> Green, otherwise Gray
  bus     : same as simple, but also marks the element as the reference Bus
            for derived types
  derived : no Modbus read; Red if the reference Bus is Red and the upstream
            element (the segment ending right before) is Red; otherwise Green
"""
import json
import threading
from pathlib import Path
from typing import Optional

RULES = ["simple", "breaker", "bus", "derived"]

DEFAULT_TYPES = [
    {"name": "Incom", "rule": "simple"},
    {"name": "Breaker", "rule": "breaker"},
    {"name": "Bus", "rule": "bus"},
    {"name": "Tie", "rule": "simple"},
    {"name": "Feeder", "rule": "derived"},
]


class TypeStore:
    def __init__(self, data_file: Path):
        self._file = data_file
        self._lock = threading.Lock()
        self._types: list[dict] = []
        self._load()

    def _load(self):
        if self._file.exists():
            self._types = json.loads(self._file.read_text()).get("types", [])
        else:
            self._types = [dict(t) for t in DEFAULT_TYPES]
            self._save()

    def _save(self):
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"types": self._types}, indent=2))
        tmp.replace(self._file)

    @staticmethod
    def _validate(row: dict) -> dict:
        name = str(row.get("name", "")).strip()
        rule = row.get("rule", "simple")
        if not name:
            raise ValueError("the type name cannot be empty")
        if rule not in RULES:
            raise ValueError(f"invalid rule: {rule!r} (valid: {RULES})")
        return {"name": name, "rule": rule}

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(t) for t in self._types]

    def exists(self, name: str) -> bool:
        with self._lock:
            return any(t["name"] == name for t in self._types)

    def rule_for(self, name: str) -> str:
        """Rule of the type; 'simple' if the type no longer exists (stale data)."""
        with self._lock:
            return next((t["rule"] for t in self._types if t["name"] == name), "simple")

    def add(self, row: dict) -> dict:
        clean = self._validate(row)
        with self._lock:
            if any(t["name"] == clean["name"] for t in self._types):
                raise ValueError(f"a type named {clean['name']!r} already exists")
            self._types.append(clean)
            self._save()
            return dict(clean)

    def update(self, name: str, row: dict) -> Optional[dict]:
        """Update the type `name`. Returns the updated type or None."""
        clean = self._validate(row)
        with self._lock:
            for i, t in enumerate(self._types):
                if t["name"] == name:
                    if clean["name"] != name and any(
                        o["name"] == clean["name"] for o in self._types
                    ):
                        raise ValueError(f"a type named {clean['name']!r} already exists")
                    self._types[i] = clean
                    self._save()
                    return dict(clean)
            return None

    def delete(self, name: str) -> bool:
        with self._lock:
            before = len(self._types)
            self._types = [t for t in self._types if t["name"] != name]
            if len(self._types) != before:
                self._save()
                return True
            return False
