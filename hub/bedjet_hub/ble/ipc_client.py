import asyncio
import json
import logging
from datetime import datetime

from bedjet_hub.ble.const import NotificationType, OperatingMode
from bedjet_hub.ble.state import DeviceMetadata, DeviceState

logger = logging.getLogger(__name__)

class BleProxyClient:
    """Proxy client that mimics BleManager but talks over UDS to the ble_daemon."""

    def __init__(self, sock_path: str = "/run/bedjet/bedjet_ble.sock"):
        self.sock_path = sock_path
        self.reader = None
        self.writer = None
        self._req_id = 0
        self._pending_requests = {}
        self._read_task = None
        self._connected = False

        # Local state cache
        self._state = DeviceState()
        self._metadata = None
        self._subscribers = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_state(self) -> DeviceState:
        return self._state

    def get_metadata(self):
        return self._metadata

    def subscribe(self, cb) -> callable:
        self._subscribers.append(cb)
        def unsub():
            if cb in self._subscribers:
                self._subscribers.remove(cb)
        return unsub

    def _notify_subscribers(self, state: DeviceState):
        for cb in self._subscribers:
            try:
                cb(state)
            except Exception as e:
                logger.error(f"Error in proxy subscriber: {e}")

    def _parse_state(self, data: dict) -> DeviceState:
        # Reconstruct DeviceState handling enums and dates
        state = DeviceState()
        for k, v in data.items():
            if hasattr(state, k):
                if k == "mode" and isinstance(v, int):
                    setattr(state, k, OperatingMode(v))
                elif k == "notification" and isinstance(v, int):
                    setattr(state, k, NotificationType(v))
                elif k == "run_end_time" and v is not None:
                    try:
                        setattr(state, k, datetime.fromisoformat(v))
                    except Exception:
                        pass
                else:
                    setattr(state, k, v)
        return state

    def _parse_metadata(self, data: dict) -> DeviceMetadata:
        meta = DeviceMetadata()
        for k, v in data.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        return meta

    async def connect(self):
        """Connects to the UDS daemon with exponential backoff (Edge Case 6)."""
        retries = 0
        while not self._connected:
            try:
                self.reader, self.writer = await asyncio.open_unix_connection(self.sock_path)
                self._connected = True
                self._read_task = asyncio.create_task(self._read_loop())
                logger.info(f"Connected to BLE UDS at {self.sock_path}")
            except Exception as e:
                retries += 1
                delay = min(5.0, 0.5 * (1.5 ** retries))
                logger.warning(f"Waiting for BLE daemon (attempt {retries})... ({e})")
                await asyncio.sleep(delay)

    async def disconnect(self):
        """Cleanly disconnects."""
        self._connected = False

        # Cancel all pending requests so they don't hang (Edge Case 3)
        for _req_id, fut in list(self._pending_requests.items()):
            if not fut.done():
                fut.set_exception(ConnectionError("IPC disconnected"))
        self._pending_requests.clear()

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    async def _read_loop(self):
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break

                payload = json.loads(line.decode())

                # Handle Events
                if payload.get("event") == "state_update":
                    self._state = self._parse_state(payload.get("data", {}))
                    self._notify_subscribers(self._state)
                    continue
                elif payload.get("event") == "metadata_update":
                    self._metadata = self._parse_metadata(payload.get("data", {}))
                    continue

                # Handle Command Responses
                req_id = payload.get("req_id")
                if req_id is not None and req_id in self._pending_requests:
                    fut = self._pending_requests.pop(req_id)
                    if not fut.done():
                        if payload.get("status") == "ok":
                            fut.set_result(payload)
                        else:
                            fut.set_exception(Exception(payload.get("error", "Unknown error")))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"BleProxyClient read loop error: {e}")
        finally:
            await self.disconnect()
            # If the daemon dies, start trying to reconnect
            asyncio.create_task(self.connect())

    async def _send_command(self, cmd: str, args: dict = None):
        if not self._connected:
            raise ConnectionError("Not connected to BLE daemon")

        self._req_id += 1
        req_id = self._req_id

        fut = asyncio.get_event_loop().create_future()
        self._pending_requests[req_id] = fut

        payload = {"req_id": req_id, "cmd": cmd, "args": args or {}}
        self.writer.write(json.dumps(payload).encode() + b"\n")
        await self.writer.drain()

        try:
            res = await asyncio.wait_for(fut, timeout=10.0)
            return res.get("result")
        except TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"IPC command {cmd} timed out") from None

    def __getattr__(self, name):
        """Magic method to forward all missing async methods to the remote daemon."""
        # Only proxy typical bedjet commands
        if name.startswith("set_") or name.startswith("activate_") or name == "sync_clock":
            async def wrapper(**kwargs):
                return await self._send_command(name, kwargs)
            return wrapper
        raise AttributeError(f"'BleProxyClient' object has no attribute '{name}'")
