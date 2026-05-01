import asyncio
import json

import pytest

# We are intentionally importing a module that doesn't exist yet to prove it fails
from bedjet_hub.ble.ipc_server import start_ipc_server


@pytest.mark.asyncio
async def test_ipc_server_responds_to_command(tmp_path):
    sock_path = str(tmp_path / "test_ble.sock")

    # 1. Mock the Bleak/BedJet hardware
    class MockBle:
        def __init__(self):
            self.temp = None

        async def set_temperature(self, c):
            self.temp = c
            return True

    ble = MockBle()

    # 2. Start the UDS IPC server
    server, task = await start_ipc_server(ble, sock_path)

    try:
        # 3. Connect a dummy client
        reader, writer = await asyncio.open_unix_connection(sock_path)

        # 4. Send a JSON command to change temperature
        cmd = {"req_id": 1, "cmd": "set_temperature", "args": {"c": 25.0}}
        writer.write(json.dumps(cmd).encode() + b"\n")
        await writer.drain()

        # 5. Wait for the JSON response
        response_line = await asyncio.wait_for(reader.readline(), timeout=1.0)
        response = json.loads(response_line.decode())

        # 6. Verify the response and the side-effect on the MockBle
        assert response["req_id"] == 1
        assert response["status"] == "ok"
        assert ble.temp == 25.0
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
        task.cancel()
