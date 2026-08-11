"""Cliente Modbus TCP asíncrono (equivale al modbus-client 'plc1' de Node-RED)."""
import asyncio
import logging

from pymodbus.client import AsyncModbusTcpClient

log = logging.getLogger(__name__)


class ModbusReader:
    def __init__(self, host: str, port: int, unit: int = 1, timeout_s: float = 1.0):
        self._host = host
        self._port = port
        self._unit = unit
        self._timeout = timeout_s
        self._client: AsyncModbusTcpClient | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> AsyncModbusTcpClient:
        if self._client is None or not self._client.connected:
            self._client = AsyncModbusTcpClient(
                self._host, port=self._port, timeout=self._timeout
            )
            await self._client.connect()
        if not self._client.connected:
            raise ConnectionError(f"No hay conexión Modbus con {self._host}:{self._port}")
        return self._client

    async def read_holding(self, address: int, count: int) -> list:
        async with self._lock:
            client = await self._ensure_connected()
            rr = await client.read_holding_registers(address, count=count, slave=self._unit)
            if rr.isError():
                raise IOError(f"Error Modbus leyendo addr={address}: {rr}")
            return list(rr.registers)

    async def write_register(self, address: int, value: int):
        async with self._lock:
            client = await self._ensure_connected()
            rq = await client.write_register(address, value, slave=self._unit)
            if rq.isError():
                raise IOError(f"Error Modbus escribiendo addr={address}: {rq}")

    async def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None
