# CLAUDE.md — project guide for future sessions

Read this before touching anything. It captures the architecture, the environment
quirks of this Raspberry Pi, and the decisions already made, so work can continue
without re-discovering them.

## What this project is

A standalone rewrite (Python) of a lighting **mimic panel for electrical
switchboards**: LED strips represent one-line-diagram elements (incomers, breakers,
buses, feeders) and light up in colors derived from PLC states read over Modbus TCP.

It replaces an older Node-RED project that still lives on this Pi
(`~/.node-red/flows.json`, service `nodered.service`, port 1880). The color logic was
ported 1:1 from its 'Print' and 'get color' flows. Node-RED is kept as reference but
must be **stopped** before this app can drive the physical LEDs (both grab the same
PWM/DMA hardware).

The user (Nelson) communicates in Spanish; **all code, UI and docs are in English**
(explicit requirement since commit `5b4cf26`).

## Architecture

```
Browser ⇄ WebSocket /ws + REST /api/*          (web/: vanilla JS, no build step)
              │
        FastAPI (switchboard/main.py)          wires everything, owns the API
              │
        MimicEngine (engine.py)                poll loop: every poll_interval_s
              │                                resolve segments → colors → paint
   ┌──────────┼──────────────┬───────────────┐
 SegmentStore ElementStore TypeStore StripStore   (JSON persistence in data/)
              │
        ModbusPool (modbus_client.py)          async client per (host,port)
        StripManager (leds.py)                 routes paint by strip id:
          ├─ Ws281xBank: ≤2 local PWM strips   single ws2811_init, low-level API
          ├─ WledSender: ESP32/WLED strips     UDP DNRGB, fire-and-forget
          └─ MockBank fallback                 when no root/hardware (dev mode)
```

### Data model (data/*.json — LIVE USER DATA, never clobber blindly)

- `strips.json` — strips with id+name. `kind: "pwm"` (the ≤2 local ones, seeded from
  config.json, renameable only) or `kind: "wled"` (host/port/count, full CRUD, hot
  synced via `StripManager.sync()`).
- `types.json` — object types, each with a color `rule`: `simple` | `breaker` |
  `bus` | `derived` (see colors.py docstring for the register semantics).
- `elements.json` — named devices (e.g. "Main A") with a type and per-element Modbus
  params `{host, port, unit, address}`. Elements can live on different PLCs.
- `segments.json` — the mimic table: `{strip, start, end, element_id}` (LEDs are
  1-based). Overlap within a strip is rejected by `SegmentStore._find_overlap`.

Deletion protections cascade: type in use by elements → 400; element assigned to
segments → 400; strip with segments → 400; PWM strips undeletable.

### Engine behaviors worth knowing

- Virtual buffers per strip can exceed the physical LED count (`display_count`):
  the UI grows, physical strip renders only what fits, extra LEDs drawn dashed.
- Test mode freezes polling, highlights the selected segment blue, and
  `/api/test-led/{strip}/{led}` toggles single LEDs blue (wiring checks).
- `derived` color rule: Red iff reference bus (first `bus`-rule row) is Red AND the
  upstream segment (whose `end == start-1`) is Red. Order of the segment table
  matters for resolution — rows resolve top to bottom.

## Environment (this Raspberry Pi)

- **Python 3.9.2** — several gotchas below exist because of this version.
- venv at `.venv`, created with `--system-site-packages` so the system-wide
  `rpi_ws281x` is importable. Deps: fastapi, uvicorn[standard], pymodbus 3.8.
- **Port 8085** for HTTP (8080, 8081, 8090 are taken by other services on this Pi;
  1880 is Node-RED). PLC simulator on **5020** (5050 is taken by Node-RED's own
  modbus-server while it runs).
- LEDs need **root** (`/dev/mem`); without root the app logs a warning and uses the
  mock driver — that's the normal dev mode. The physical render path is only
  exercised when run with sudo AND Node-RED is stopped.
- GitHub remote uses **SSH** (`git@github.com:nel7601/Switchboard_mimic.git`), the
  user's key is registered; HTTPS has no credentials. Tag `vista-unificada` marks
  the pre-tabs UI variant (kept on purpose as a fallback).

### Running the dev instance

```bash
cd /home/nelson/Switchboard_mimic
.venv/bin/python simulator/plc_sim.py &          # if not already running
.venv/bin/python -m switchboard.main &           # mock LEDs, port 8085
```

To restart, kill by PID — a plain `pkill -f switchboard` matches your own shell
wrapper and kills it (exit 144). Use:

```bash
for p in $(pgrep -f "switchboard"); do
  readlink /proc/$p/exe | grep -q python && kill $p
done
```

Quick sanity: `curl -s localhost:8085/api/state | python3 -m json.tool` — check
`modbus_ok: true` and segment colors. The user often has the web UI open and edits
data while you work: **re-read data files / API state before assuming their
contents**, and never reseed data/ without asking.

## Pitfalls already hit (do not re-learn these)

1. **Python 3.9 + asyncio primitives**: an `asyncio.Lock()` created at import time
   binds to the wrong event loop and explodes under contention ("Future attached to
   a different loop"). All locks are created lazily inside the running loop
   (see ModbusPool._get_lock, MimicEngine._refresh_lock). Keep doing this.
2. **Dual PWM strips**: two `PixelStrip` instances conflict (shared PWM peripheral +
   DMA 10). `Ws281xBank` configures both channels in ONE `ws2811_init` via the
   low-level `rpi_ws281x.ws` API. Unused channel gets count=0.
3. **pymodbus 3.8 API**: `read_holding_registers(address, count=..., slave=...)`;
   the simulator datastore uses a +1 offset (`zero_mode` default).
4. **WLED protocol**: DNRGB packets `[4, timeout, idxHi, idxLo, rgb...]`, ≤489 LEDs
   per datagram, timeout 255 = stay in realtime mode. Untested against a real ESP32
   so far (see Pending).
5. FastAPI redirects `DELETE /api/segments/` (trailing slash) to the clear-all
   endpoint — an empty id variable in a curl test once wiped the table. Data was
   restored from git; be careful with shell-built URLs.

## State of deployment

The app is NOT yet the production service: `nodered.service` is still enabled and
owns the LED hardware. The systemd units exist (`systemd/*.service`) but are not
installed. Migration plan (when the user says go):
`sudo systemctl disable --now nodered` → copy units → `sudo systemctl enable --now
plc-simulator switchboard` (simulator only until a real PLC is configured).

A dev instance (mock LEDs) + the PLC simulator are usually left running on 8085/5020
so the user can play with the UI.

## Pending / next steps

- **Hardware validation**: dual-PWM physical render (needs sudo + Node-RED stopped)
  and a real ESP32/WLED strip receiving DNRGB. Code follows the official patterns
  but neither has run against real hardware yet.
- Real PLC integration: element addresses are provisional, pointing at the local
  simulator (127.0.0.1:5020). The register map is documented in simulator/plc_sim.py.
- Possible future ideas the user has hinted at: more per-type flexibility, richer
  mimic layouts. Nothing committed.

## Testing conventions used so far

No test framework yet — verification is curl-based against the running instance
(see git history for examples: overlap cases, type/element/strip CRUD + protections,
color scenarios via `/api/modbus/write` + `/api/refresh`). If adding pytest, mock
the ModbusPool and use MockBank; stores take a tmp path.
