"""Mimic color logic (port of the Node-RED 'get color' flow).

The color no longer depends on the type's name but on its rule (see
typestore.RULES). Registers per element (FC3, 5 registers from `station`):
  regs[0] = closed / active
  regs[1] = open / fault
  regs[2] = tripped (breaker rule only)
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
    # simple and bus share the same mapping
    return "Red" if regs[0] == 1 else "Green"


def derived_color(resolved_rows: list, start: int) -> str:
    """'derived' rule: the element is not read over Modbus. It inherits Red only
    if the reference Bus (first segment with the 'bus' rule) is Red and the
    upstream element (the segment whose last LED is start-1) is Red."""
    bus_color = next((r["color"] for r in resolved_rows if r.get("rule") == "bus"), "")
    upstream_end = start - 1
    upstream_color = next((r["color"] for r in resolved_rows if r["end"] == upstream_end), "")
    if bus_color == "Red" and upstream_color == "Red":
        return "Red"
    return "Green"
