import asyncio
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from enum import Enum

from bedjet_hub.ble.manager import BleManager

logger = logging.getLogger(__name__)

class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        return super().default(o)

class IpcServer:
    def __init__(self, ble: BleManager, sock_path: str):
        self.ble = ble
        self.sock_path = sock_path
        self.clients = set()
        self._server = None
        self._unsub = None

    def _broadcast_state(self, state):
        if not self.clients:
            return

        # Serialize the state
        data = asdict(state)
        payload = json.dumps({"event": "state_update", "data": data}, cls=EnhancedJSONEncoder) + "\n"

        # Dispatch writes without blocking the event loop (Edge Case 4)
        for writer in list(self.clients):
            try:
                writer.write(payload.encode())
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                self.clients.discard(writer)

    def _broadcast_metadata(self, meta):
        if not self.clients or not meta:
            return
        data = asdict(meta)
        payload = json.dumps({"event": "metadata_update", "data": data}, cls=EnhancedJSONEncoder) + "\n"
        for writer in list(self.clients):
            try:
                writer.write(payload.encode())
            except Exception:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.clients.add(writer)

        # Send initial full state immediately upon connection (Edge Case 2)
        try:
            state = self.ble.get_state()
            if state:
                self._broadcast_state(state)
            meta = self.ble.get_metadata()
            if meta:
                self._broadcast_metadata(meta)
        except Exception:
            pass

        try:
            while True:
                # Enforce strict byte limit (Edge Case 5)
                line = await asyncio.wait_for(reader.readline(), timeout=None)
                if not line:
                    break

                # We limit the max size of a line manually just in case
                if len(line) > 4096:
                    logger.warning("Payload too large, dropping")
                    break

                payload = json.loads(line.decode())
                req_id = payload.get("req_id")
                cmd = payload.get("cmd")
                args = payload.get("args", {})

                if hasattr(self.ble, cmd) and callable(getattr(self.ble, cmd)):
                    try:
                        func = getattr(self.ble, cmd)
                        if asyncio.iscoroutinefunction(func):
                            res = await func(**args)
                        else:
                            res = func(**args)
                        response = {"req_id": req_id, "status": "ok", "error": None, "result": res}
                    except Exception as e:
                        response = {"req_id": req_id, "status": "error", "error": str(e)}
                else:
                    response = {"req_id": req_id, "status": "error", "error": "unknown command"}

                writer.write(json.dumps(response, cls=EnhancedJSONEncoder).encode() + b"\n")
                await writer.drain()

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            self.clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        # Edge Case 1: Pre-bind cleanup
        if os.path.exists(self.sock_path):
            try:
                os.unlink(self.sock_path)
            except FileNotFoundError:
                pass

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(self.sock_path), exist_ok=True)

        self._server = await asyncio.start_unix_server(self._handle_client, path=self.sock_path)

        # Edge Case 7: Explicitly set permissions for User Isolation
        os.chmod(self.sock_path, 0o660)

        # Hook the broadcast
        self._unsub = self.ble.subscribe(self._broadcast_state)
        return self._server

    async def stop(self):
        if self._unsub:
            self._unsub()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

async def start_ipc_server(ble: BleManager, sock_path: str):
    """Wrapper to match original test signature."""
    server_obj = IpcServer(ble, sock_path)
    server = await server_obj.start()
    task = asyncio.create_task(asyncio.sleep(0))
    return server, task
