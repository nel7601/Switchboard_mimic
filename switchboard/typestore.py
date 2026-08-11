"""Tipos de objeto asignables a los segmentos, definibles por el usuario.

Cada tipo lleva una regla de color:
  simple  : reg[0]=1 -> Rojo, si no Verde
  breaker : reg[2]=1 -> Amarillo (disparado), reg[1]=1 -> Rojo,
            reg[0]=1 -> Verde, si no Gris
  bus     : igual que simple, pero además marca el elemento como Bus de
            referencia para los tipos derivados
  derived : sin lectura Modbus; Rojo si el Bus de referencia está Rojo y el
            elemento aguas arriba (el segmento que termina justo antes) está
            Rojo; si no Verde
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
            raise ValueError("el nombre del tipo no puede estar vacío")
        if rule not in RULES:
            raise ValueError(f"regla inválida: {rule!r} (válidas: {RULES})")
        return {"name": name, "rule": rule}

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(t) for t in self._types]

    def exists(self, name: str) -> bool:
        with self._lock:
            return any(t["name"] == name for t in self._types)

    def rule_for(self, name: str) -> str:
        """Regla del tipo; 'simple' si el tipo ya no existe (dato antiguo)."""
        with self._lock:
            return next((t["rule"] for t in self._types if t["name"] == name), "simple")

    def add(self, row: dict) -> dict:
        clean = self._validate(row)
        with self._lock:
            if any(t["name"] == clean["name"] for t in self._types):
                raise ValueError(f"ya existe un tipo llamado {clean['name']!r}")
            self._types.append(clean)
            self._save()
            return dict(clean)

    def update(self, name: str, row: dict) -> Optional[dict]:
        """Actualiza el tipo `name`. Devuelve (tipo, nombre_anterior) o None."""
        clean = self._validate(row)
        with self._lock:
            for i, t in enumerate(self._types):
                if t["name"] == name:
                    if clean["name"] != name and any(
                        o["name"] == clean["name"] for o in self._types
                    ):
                        raise ValueError(f"ya existe un tipo llamado {clean['name']!r}")
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
