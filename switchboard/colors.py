"""Lógica de colores del mímico (port de 'get color' de Node-RED).

El color ya no depende del nombre del tipo sino de su regla (ver typestore.RULES).
Registros por elemento (FC3, 5 registros desde `station`):
  regs[0] = cerrado / activo
  regs[1] = abierto / falla
  regs[2] = disparado (solo regla breaker)
"""

COLOR_RGB = {
    "Red": (255, 0, 0),
    "Yellow": (255, 255, 0),
    "Green": (0, 255, 0),
    "Gray": (169, 169, 169),
    "Blue": (0, 0, 255),
    "Off": (0, 0, 0),
}


def color_from_registers(rule: str, regs: list) -> str:
    if rule == "breaker":
        if regs[2] == 1:
            return "Yellow"
        if regs[1] == 1:
            return "Red"
        if regs[0] == 1:
            return "Green"
        return "Gray"
    # simple y bus comparten mapeo
    return "Red" if regs[0] == 1 else "Green"


def derived_color(resolved_rows: list, start: int) -> str:
    """Regla 'derived': el elemento no se lee por Modbus. Hereda Rojo solo si el
    Bus de referencia (primer segmento con regla 'bus') está Rojo y el elemento
    aguas arriba (el segmento cuyo LED final es start-1) está Rojo."""
    bus_color = next((r["color"] for r in resolved_rows if r.get("rule") == "bus"), "")
    upstream_end = start - 1
    upstream_color = next((r["color"] for r in resolved_rows if r["end"] == upstream_end), "")
    if bus_color == "Red" and upstream_color == "Red":
        return "Red"
    return "Green"
