import asyncio
import logging
import signal

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
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    
    def signal_handler(sig_name):
        logger.info(f"Received {sig_name}, cancelling main task...")
        if main_task:
            main_task.cancel()

    for sig, name in ((signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")):
        loop.add_signal_handler(sig, signal_handler, name)

    cfg = Config()
    ble = BleManager(address=cfg.bedjet_address)

    sock_path = "/run/bedjet/bedjet_ble.sock"
    logger.info(f"Starting BLE UDS Server at {sock_path}")
    server, _ = await start_ipc_server(ble, sock_path=sock_path)

    await try_initial_connect(ble)
    await ble.start_auto_reconnect()

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        logger.info("Main task cancelled, beginning shutdown sequence...")
    finally:
        server.close()
        await server.wait_closed()
        try:
            await asyncio.wait_for(ble.disconnect(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout while disconnecting BLE, forcing exit.")
        except Exception as e:
            logger.error(f"Error during BLE disconnect: {e}")

if __name__ == "__main__":
    asyncio.run(main())
