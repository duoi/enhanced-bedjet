import asyncio
import json

import pytest

from bedjet_hub.ble.ipc_server import start_ipc_server
from bedjet_hub.ble.state import DeviceMetadata


@pytest.mark.asyncio
async def test_ipc_server_responds_to_command(tmp_path):
    sock_path = str(tmp_path / "test_ble.sock")

    # 1. Mock the Bleak/BedJet hardware
    class MockBle:
        def __init__(self):
            self.temp = None
            self.subscribers = []
            self.metadata_subscribers = []

        async def set_temperature(self, c):
            self.temp = c
            return True

        def subscribe(self, callback):
            self.subscribers.append(callback)
            return lambda: self.subscribers.remove(callback)

        def subscribe_metadata(self, callback):
            self.metadata_subscribers.append(callback)
            return lambda: self.metadata_subscribers.remove(callback)

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


@pytest.mark.asyncio
async def test_metadata_reaches_a_client_that_connected_before_the_reads_finished(tmp_path):
    """Regression: the hub caches the metadata snapshot pushed at connect time.

    The daemon's initial biodata reads are several slow GATT round-trips, while
    the hub attaches to the socket as soon as it starts — so in practice the hub
    receives the *empty* snapshot. Unless the daemon publishes the metadata again
    once the reads complete, the hub serves blank firmware/memory/biorhythm
    values for the lifetime of the process, restarting the hub being the only
    cure. The reads themselves always worked.
    """
    sock_path = str(tmp_path / "test_ble.sock")

    class MockBle:
        def __init__(self):
            self.state_subscribers = []
            self.metadata_subscribers = []
            self.metadata = DeviceMetadata(address="AA:BB")

        def get_state(self):
            return None

        def subscribe(self, callback):
            self.state_subscribers.append(callback)
            return lambda: self.state_subscribers.remove(callback)

        def get_metadata(self):
            return self.metadata

        def subscribe_metadata(self, callback):
            self.metadata_subscribers.append(callback)
            return lambda: self.metadata_subscribers.remove(callback)

        def finish_initial_reads(self):
            """The daemon's GATT reads completing, after the client attached."""
            self.metadata.name = "BEDJET-73D8"
            self.metadata.firmware_version = "V1.20 (140)"
            self.metadata.memory_names = ["MEMORY 1", None, None]
            self.metadata.biorhythm_names = ["hot to cold", None, None]
            for callback in list(self.metadata_subscribers):
                callback(self.metadata)

    ble = MockBle()
    server, task = await start_ipc_server(ble, sock_path)

    try:
        reader, writer = await asyncio.open_unix_connection(sock_path)

        # 1. The snapshot sent on attach: the reads have not finished yet.
        first = json.loads((await asyncio.wait_for(reader.readline(), timeout=1.0)).decode())
        assert first["event"] == "metadata_update"
        assert first["data"]["name"] == ""

        # 2. The reads complete. The already-attached client must be told, or it
        #    keeps serving the empty snapshot it cached above.
        ble.finish_initial_reads()
        second = json.loads((await asyncio.wait_for(reader.readline(), timeout=1.0)).decode())
        assert second["event"] == "metadata_update"
        assert second["data"]["name"] == "BEDJET-73D8"
        assert second["data"]["firmware_version"] == "V1.20 (140)"
        assert second["data"]["memory_names"] == ["MEMORY 1", None, None]
        assert second["data"]["biorhythm_names"] == ["hot to cold", None, None]
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await server.wait_closed()
        task.cancel()
