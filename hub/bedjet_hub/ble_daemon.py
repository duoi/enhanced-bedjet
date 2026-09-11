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


#: How often the BLE watchdog inspects the connection for stale notifications.
WATCHDOG_INTERVAL_SECONDS = 60


async def stale_data_watchdog(ble, on_stale, interval_seconds: float = WATCHDOG_INTERVAL_SECONDS):
    """Poll ``ble`` for stale notifications and call ``on_stale`` when they stop.

    Runs until cancelled. A failing check is logged and retried rather than
    killing the loop: this watchdog is the last line of defence against a wedged
    Bluetooth link, so silently dying on its first error would be worse than not
    running it at all.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            if ble.is_connected and await ble.check_stale_data():
                logger.error("Watchdog: stale data detected! Exiting to trigger restart.")
                on_stale()
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Watchdog check failed; continuing to watch.")


async def main():
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()

    def request_shutdown():
        if main_task:
            main_task.cancel()

    def signal_handler(sig_name):
        logger.info(f"Received {sig_name}, cancelling main task...")
        request_shutdown()

    for sig, name in ((signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")):
        loop.add_signal_handler(sig, signal_handler, name)

    cfg = Config()
    ble = BleManager(address=cfg.bedjet_address)

    sock_path = "/run/bedjet/bedjet_ble.sock"
    logger.info(f"Starting BLE UDS Server at {sock_path}")
    server, _ = await start_ipc_server(ble, sock_path=sock_path)

    await try_initial_connect(ble)
    await ble.start_auto_reconnect()

    # Hold a reference to the task: an unreferenced task may be garbage
    # collected mid-run, which would silently disable the watchdog.
    watchdog = asyncio.create_task(stale_data_watchdog(ble, request_shutdown))
    logger.info(f"BLE watchdog running every {WATCHDOG_INTERVAL_SECONDS}s")

    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        logger.info("Main task cancelled, beginning shutdown sequence...")
    finally:
        watchdog.cancel()
        server.close()
        await server.wait_closed()
        try:
            await asyncio.wait_for(ble.disconnect(), timeout=5.0)
        except TimeoutError:
            logger.warning("Timeout while disconnecting BLE, forcing exit.")
        except Exception as e:
            logger.error(f"Error during BLE disconnect: {e}")

if __name__ == "__main__":
    asyncio.run(main())
