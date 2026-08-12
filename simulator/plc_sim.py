"""Modbus TCP PLC simulator (replaces the Node-RED 'Modbus Simulation' tab).

Serves holding registers on 127.0.0.1:5020. States are changed by writing
registers, either from the web app's 'PLC simulator' panel or with any
Modbus client (FC6/FC16).

Register map used by the original project (5 registers per element starting
at `station`):
  104: Incom            (reg 0: 1=closed→Red, 0=Green)
  105-109: Utility breaker (105=closed, 106=open, 107=tripped, 108/109=test)
  110: Bus A
  115-119: Feeder A breaker

Usage:  .venv/bin/python simulator/plc_sim.py [--port 5020]
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

REGISTER_SPACE = 20000  # same size as the Node-RED modbus-server

# Demo initial state: incomer closed, breakers closed, bus energized
INITIAL = {104: 1, 105: 1, 110: 1, 115: 1}


async def main(host: str, port: int):
    block = ModbusSequentialDataBlock(0, [0] * (REGISTER_SPACE + 1))
    for addr, value in INITIAL.items():
        block.setValues(addr + 1, [value])  # the datastore uses a +1 offset
    slave = ModbusSlaveContext(hr=block)
    context = ModbusServerContext(slaves=slave, single=True)
    log.info("PLC simulator listening on %s:%d (unit 1)", host, port)
    await StartAsyncTcpServer(context=context, address=(host, port))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Modbus TCP PLC simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5020)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
