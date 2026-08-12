# Switchboard Mimic

Lighting mimic panel for an electrical switchboard on WS2812B LED strips, driven
by a Raspberry Pi. Standalone rewrite of the original Node-RED project — same
logic, no Node-RED dependency.

## What it does

- The switchboard **elements** (Mimic A, Main B, Tie, Bus A, Feeder A1, …) are
  defined in the *Elements* view (`/elements`): each one with its type and its own
  Modbus parameters — IP, port, device/unit ID and first register address. Each
  element can live on a different PLC (per-host connection pool).
- A **segment table** (*Mimic* view, `/`) maps LED ranges (`start`–`end`, 1-based)
  to those elements: just range + element. A LED can only belong to one segment
  per strip (overlap is rejected).
- **Object types** are defined in the *Settings* page (`/settings`). Each type
  carries a **color rule**:

  | Rule | Behavior |
  |---|---|
  | `simple` | `reg[0]=1` → Red · otherwise → Green |
  | `breaker` | `reg[2]=1` → Yellow (tripped) · `reg[1]=1` → Red · `reg[0]=1` → Green · otherwise → Gray |
  | `bus` | Like `simple`, and marks the element as the reference Bus for derived types |
  | `derived` | No Modbus read: Red if the reference Bus is Red **and** the upstream element (the segment ending right before) is Red; otherwise Green |

  Default types: Incom (`simple`), Breaker (`breaker`), Bus (`bus`), Tie (`simple`),
  Feeder (`derived`).
- Supports **multiple LED strips**:
  - Up to 2 local **PWM strips** on the Raspberry Pi (`config.json` → `strips`):
    channel 0 on GPIO 12/18 and channel 1 on GPIO 13/19, driven from a single
    ws2811 initialization (they share the PWM peripheral and DMA). They are fixed;
    Settings only allows renaming them.
  - Unlimited **WLED strips** (ESP32 controllers on the network), created from
    Settings with name, host/IP, port and LED count. Painted with WLED's DNRGB
    realtime UDP protocol (dependency-free, auto-chunked for long strips). Adds,
    edits and removals apply live.
  - Each strip appears as a tab in the Mimic view, with its own segment table.
- A **poller** reads Modbus TCP (FC3, 5 registers per element, using each
  element's connection parameters) and computes every segment's color from its
  type's rule.
- The physical strips are painted with those colors. The view shows at least each
  strip's configured LEDs and **grows automatically** when the table assigns LEDs
  beyond that; LEDs past the physical strip are drawn with a dashed border.
- **Test mode**: freezes refreshing, highlights the selected segment in blue, and
  lets you click individual LEDs to toggle them blue on the physical strip — handy
  to verify real positions and wiring.

## Structure

```
switchboard/        backend: FastAPI + WebSocket, Modbus poller, LED drivers
  main.py           REST API + WS + static files
  engine.py         refresh & paint cycle (port of the 'Print' flow)
  colors.py         color logic (port of the 'get color' flow)
  store.py          LED→element assignment persisted in data/segments.json
  elementstore.py   elements with type and Modbus parameters (data/elements.json)
  typestore.py      object types and their color rule (data/types.json)
  stripstore.py     named LED strips: local pwm + remote wled (data/strips.json)
  leds.py           ws281x dual-PWM bank + WLED UDP sender, mock fallback
  modbus_client.py  async Modbus TCP client pool
simulator/plc_sim.py  Modbus PLC simulator (replaces the 'Modbus Simulation' tab)
web/                vanilla JS frontend (no build step)
systemd/            service units
config.json         PWM strips (count, GPIO, brightness, channel), Modbus, HTTP port
```

## Installation (Raspberry Pi)

```bash
git clone https://github.com/nel7601/Switchboard_mimic.git
cd Switchboard_mimic
python3 -m venv --system-site-packages .venv   # system-site to use the system rpi_ws281x
.venv/bin/pip install -r requirements.txt
```

`rpi_ws281x` must be installed system-wide (it already is if the Pi ran
node-red-node-pi-neopixel): `sudo pip3 install rpi_ws281x`.

## Usage

```bash
# PLC simulator (when there is no real PLC):
.venv/bin/python simulator/plc_sim.py            # Modbus TCP on 127.0.0.1:5020

# Application (root required for the LED strips; without root it uses a mock driver):
sudo .venv/bin/python -m switchboard.main
```

Web app at `http://<pi-ip>:8085`.

For a real PLC, set each element's Modbus parameters in the Elements view.

### As a service

```bash
sudo cp systemd/switchboard.service /etc/systemd/system/
sudo cp systemd/plc-simulator.service /etc/systemd/system/   # optional, simulation only
sudo systemctl enable --now plc-simulator switchboard
```

> **Note:** the LED strips (PWM GPIOs) can only be used by one process at a time.
> If Node-RED is still running the old project, stop it first:
> `sudo systemctl disable --now nodered`

## API

| Method | Route | Description |
|---|---|---|
| GET | `/api/state` | Full state: segments with color and rule, pixels per strip, mode |
| GET/POST | `/api/segments` | List / add segment |
| PUT/DELETE | `/api/segments/{id}` | Update / delete segment |
| DELETE | `/api/segments` | Clear the table (`?strip=N` clears a single strip) |
| GET/POST | `/api/strips` | List strips / add WLED strip (name, host, port, LEDs) |
| PUT/DELETE | `/api/strips/{id}` | Rename (PWM and WLED) or edit/delete (WLED only, blocked while it has segments) |
| GET/POST | `/api/elements` | List / add elements (name, type, Modbus params) |
| PUT/DELETE | `/api/elements/{id}` | Update / delete element (blocked while assigned) |
| GET/POST | `/api/types` | List / add object types |
| PUT/DELETE | `/api/types/{name}` | Update (renames cascade) / delete type (blocked while in use) |
| POST | `/api/refresh` | Force a refresh pass |
| POST | `/api/test-mode/{bool}` | Test mode (freezes refresh, highlights selection) |
| POST | `/api/test-led/{strip}/{led}` | Toggle a single LED blue (test mode) |
| POST | `/api/select/{id}` | Select a segment (0 = none) |
| POST | `/api/modbus/write` | Write a register `{address, value, host?, port?, unit?}` (simulation) |
| WS | `/ws` | Real-time state push |
