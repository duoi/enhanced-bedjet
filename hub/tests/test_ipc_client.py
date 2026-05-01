import asyncio
import json

import pytest

# Intentionally importing module that doesn't exist yet
from bedjet_hub.ble.ipc_client import BleProxyClient


@pytest.mark.asyncio
async def test_ipc_client_send_command(tmp_path):
    sock_path = str(tmp_path / "test_client.sock")

    # 1. Mock the UDS Server (Daemon side)
    async def mock_handler(reader, writer):
        line = await reader.readline()
        if not line:
            return
        payload = json.loads(line.decode())

        # Echo back a success response matching the req_id
        response = {"req_id": payload["req_id"], "status": "ok", "error": None}
        writer.write(json.dumps(response).encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(mock_handler, path=sock_path)

    # 2. Test the Proxy Client
    client = BleProxyClient(sock_path)
    try:
        await client.connect()

        # This should send {"cmd": "set_temperature", "args": {"c": 20.0}}
        # and wait for the response matching req_id
        await client.set_temperature(20.0)

    finally:
        await client.disconnect()
        server.close()
        await server.wait_closed()
