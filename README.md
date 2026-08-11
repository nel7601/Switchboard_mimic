# Switchboard Mimic

Panel mímico luminoso de un cuadro eléctrico sobre una tira LED WS2812B, controlado
desde una Raspberry Pi. Reescritura como aplicación independiente del proyecto
original hecho en Node-RED — misma lógica, sin dependencia de Node-RED.

## Qué hace

- Los **elementos** del cuadro (Mimic A, Main B, Tie, Bus A, Feeder A1, …) se definen
  en la vista *Elementos* (`/elements`): cada uno con su tipo y sus parámetros Modbus
  propios — IP, puerto, device/unit ID y dirección del primer registro. Cada elemento
  puede vivir en un PLC distinto (pool de conexiones por host).
- Una **tabla de segmentos** (vista *Mímico*, `/`) asocia tramos de la tira LED
  (`start`–`end`, base 1) a esos elementos: solo rango + elemento.
- Los **tipos de objeto** se definen en la página *Settings* (`/settings`). Cada tipo
  lleva una **regla de color**:

  | Regla | Comportamiento |
  |---|---|
  | `simple` | `reg[0]=1` → Rojo · si no → Verde |
  | `breaker` | `reg[2]=1` → Amarillo (disparado) · `reg[1]=1` → Rojo · `reg[0]=1` → Verde · si no → Gris |
  | `bus` | Como `simple`, y marca el elemento como Bus de referencia para los derivados |
  | `derived` | Sin lectura Modbus: Rojo si el Bus de referencia está Rojo **y** el elemento aguas arriba (el segmento que termina justo antes) está Rojo; si no, Verde |

  Tipos por defecto: Incom (`simple`), Breaker (`breaker`), Bus (`bus`), Tie (`simple`),
  Feeder (`derived`).
- Un **poller** lee por Modbus TCP (FC3, 5 registros por elemento, con los parámetros
  de conexión de cada elemento) y calcula el color de cada segmento según la regla de
  su tipo.
- La tira LED física se pinta con esos colores. La **web app** tiene tres páginas:
  - `/` — mímico: estado en vivo de la tira y asignación rango de LEDs → elemento
    (CRUD, modo test que resalta en azul el segmento seleccionado)
  - `/elements` — elementos del cuadro con su tipo y parámetros Modbus
  - `/settings` — tipos de objeto y panel del simulador PLC (generado a partir de los
    elementos definidos)

## Estructura

```
switchboard/        backend: FastAPI + WebSocket, poller Modbus, driver LED
  main.py           API REST + WS + estáticos
  engine.py         ciclo de refresco y pintado (port del flujo 'Print')
  colors.py         lógica de colores (port del flujo 'get color')
  store.py          asignación LEDs→elemento persistida en data/segments.json
  elementstore.py   elementos con tipo y parámetros Modbus (data/elements.json)
  typestore.py      tipos de objeto y su regla de color (data/types.json)
  leds.py           driver rpi_ws281x con fallback a mock (sin hardware/root)
  modbus_client.py  cliente Modbus TCP asíncrono
simulator/plc_sim.py  simulador de PLC Modbus (reemplaza la pestaña 'Modbus Simulation')
web/                frontend vanilla JS (sin build step)
systemd/            unidades de servicio
config.json         LEDs (nº, GPIO, brillo), Modbus (host/puerto), puerto HTTP
```

## Instalación (Raspberry Pi)

```bash
git clone https://github.com/nel7601/Switchboard_mimic.git
cd Switchboard_mimic
python3 -m venv --system-site-packages .venv   # system-site para usar rpi_ws281x del sistema
.venv/bin/pip install -r requirements.txt
```

`rpi_ws281x` debe estar instalado a nivel de sistema (ya lo está si la Pi usaba
node-red-node-pi-neopixel): `sudo pip3 install rpi_ws281x`.

## Uso

```bash
# Simulador de PLC (si no hay PLC real):
.venv/bin/python simulator/plc_sim.py            # Modbus TCP en 127.0.0.1:5020

# Aplicación (root necesario para la tira LED; sin root usa driver simulado):
sudo .venv/bin/python -m switchboard.main
```

Web app en `http://<ip-de-la-pi>:8085`.

Para un PLC real, edita `config.json` → `modbus.host/port`.

### Como servicio

```bash
sudo cp systemd/switchboard.service /etc/systemd/system/
sudo cp systemd/plc-simulator.service /etc/systemd/system/   # opcional, solo simulación
sudo systemctl enable --now plc-simulator switchboard
```

> **Nota:** la tira LED (GPIO12/PWM) solo puede usarla un proceso a la vez.
> Si Node-RED sigue corriendo con el proyecto antiguo, detenlo antes:
> `sudo systemctl disable --now nodered`

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/state` | Estado completo: segmentos con color y regla, píxeles, modo |
| GET/POST | `/api/segments` | Listar / añadir segmento |
| PUT/DELETE | `/api/segments/{id}` | Actualizar / borrar segmento |
| DELETE | `/api/segments` | Vaciar tabla |
| GET/POST | `/api/elements` | Listar / añadir elementos (nombre, tipo, params Modbus) |
| PUT/DELETE | `/api/elements/{id}` | Actualizar / borrar elemento (bloqueado si está asignado) |
| GET/POST | `/api/types` | Listar / añadir tipos de objeto |
| PUT/DELETE | `/api/types/{name}` | Actualizar (renombra en cascada) / borrar tipo (bloqueado si está en uso) |
| POST | `/api/refresh` | Forzar una pasada de refresco |
| POST | `/api/test-mode/{bool}` | Modo test (congela refresco, resalta selección) |
| POST | `/api/select/{id}` | Seleccionar segmento (0 = ninguno) |
| POST | `/api/modbus/write` | Escribir registro `{address, value}` (simulación) |
| WS | `/ws` | Push de estado en tiempo real |
