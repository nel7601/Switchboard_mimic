"""Simulador de PLC Modbus TCP (reemplaza la pestaña 'Modbus Simulation' de Node-RED).

Sirve holding registers en 127.0.0.1:5020. Los estados se cambian escribiendo
registros, bien desde el panel 'Simulador' de la web app, bien con cualquier
cliente Modbus (FC6/FC16).

Mapa usado por el proyecto original (5 registros por elemento desde `station`):
  104: Incom            (reg 0: 1=cerrado→Rojo, 0=Verde)
  105-109: Breaker Utility (105=cerrado, 106=abierto, 107=disparado, 108/109=test)
  110: Bus A
  115-119: Breaker Feeder A

Uso:  .venv/bin/python simulator/plc_sim.py [--port 5020]
"""
import argparse
import asyncio
import logging

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("plc_sim")

REGISTER_SPACE = 20000  # mismo tamaño que el modbus-server de Node-RED

# Estado inicial de demo: incom cerrado, breakers cerrados, bus energizado
INITIAL = {104: 1, 105: 1, 110: 1, 115: 1}


async def main(host: str, port: int):
    block = ModbusSequentialDataBlock(0, [0] * (REGISTER_SPACE + 1))
    for addr, value in INITIAL.items():
        block.setValues(addr + 1, [value])  # datastore usa offset +1
    slave = ModbusSlaveContext(hr=block)
    context = ModbusServerContext(slaves=slave, single=True)
    log.info("Simulador PLC escuchando en %s:%d (unit 1)", host, port)
    await StartAsyncTcpServer(context=context, address=(host, port))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simulador de PLC Modbus TCP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5020)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
