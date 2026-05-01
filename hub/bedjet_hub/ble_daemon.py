import asyncio
import logging

from bedjet_hub.ble.ipc_server import start_ipc_server
from bedjet_hub.ble.manager import BleManager
from bedjet_hub.config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def try_initial_connect(ble: BleManager) -> bool:
    try:
        await ble.connect()
        return True
    except Exception as exc:
        logger.warning("Initial BLE connection failed: %s", exc)
        return False

async def main():
    cfg = Config()
    ble = BleManager(address=cfg.bedjet_address)

    # Start the Unix Socket Server *before* doing long BLE waits
    sock_path = "/run/bedjet/bedjet_ble.sock"
    logger.info(f"Starting BLE UDS Server at {sock_path}")
    server, _ = await start_ipc_server(ble, sock_path=sock_path)

    # Try connecting to hardware
    await try_initial_connect(ble)
    await ble.start_auto_reconnect()

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()
        await ble.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
