"""Lógica de colores del mímico (port de 'get color' de Node-RED).

Registros por elemento (FC3, 5 registros desde `station`):
  regs[0] = cerrado / activo
  regs[1] = abierto / falla
  regs[2] = disparado (solo Breaker)
"""

COLOR_RGB = {
    "Red": (255, 0, 0),
    "Yellow": (255, 255, 0),
    "Green": (0, 255, 0),
    "Gray": (169, 169, 169),
    "Blue": (0, 0, 255),
    "Off": (0, 0, 0),
}


def color_from_registers(seg_type: str, regs: list) -> str:
    if seg_type == "Breaker":
        if regs[2] == 1:
            return "Yellow"
        if regs[1] == 1:
            return "Red"
        if regs[0] == 1:
            return "Green"
        return "Gray"
    return "Red" if regs[0] == 1 else "Green"


def feeder_color(resolved_rows: list, feeder_start: int) -> str:
    """Un Feeder no se lee por Modbus: hereda estado del Bus y del breaker aguas arriba
    (el segmento cuyo LED final es el inmediatamente anterior al inicio del feeder)."""
    bus_color = next((r["color"] for r in resolved_rows if r["type"] == "Bus"), "")
    upstream_end = feeder_start - 1
    breaker_color = next((r["color"] for r in resolved_rows if r["end"] == upstream_end), "")
    if bus_color == "Red" and breaker_color == "Red":
        return "Red"
    return "Green"
