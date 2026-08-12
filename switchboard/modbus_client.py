"""Modbus TCP client pool: each element may live on a different PLC
(its own host/port); connections are shared and reused."""
import asyncio
import logging

from pymodbus.client import AsyncModbusTcpClient

log = logging.getLogger(__name__)


class ModbusPool:
    def __init__(self, timeout_s: float = 1.0):
        self._timeout = timeout_s
        self._clients: dict = {}  # (host, port) -> AsyncModbusTcpClient
        # On Python 3.9 an asyncio.Lock created outside the running loop binds
        # to another loop and breaks under contention: create it lazily.
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _client_for(self, host: str, port: int) -> AsyncModbusTcpClient:
        key = (host, port)
        client = self._clients.get(key)
        if client is None or not client.connected:
            client = AsyncModbusTcpClient(host, port=port, timeout=self._timeout)
            await client.connect()
            self._clients[key] = client
        if not client.connected:
            raise ConnectionError(f"No Modbus connection to {host}:{port}")
        return client

    async def read_holding(
        self, host: str, port: int, unit: int, address: int, count: int
    ) -> list:
        async with self._get_lock():
            client = await self._client_for(host, port)
            rr = await client.read_holding_registers(address, count=count, slave=unit)
            if rr.isError():
                raise IOError(f"Modbus error reading {host}:{port} addr={address}: {rr}")
            return list(rr.registers)

    async def write_register(self, host: str, port: int, unit: int, address: int, value: int):
        async with self._get_lock():
            client = await self._client_for(host, port)
            rq = await client.write_register(address, value, slave=unit)
            if rq.isError():
                raise IOError(f"Modbus error writing {host}:{port} addr={address}: {rq}")

    async def close(self):
        async with self._get_lock():
            for client in self._clients.values():
                client.close()
            self._clients.clear()
