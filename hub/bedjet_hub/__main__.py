import asyncio
import logging

import uvicorn
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from .api.server import create_app
from .ble.manager import BleManager
from .config import Config
from .db.database import Database
from .scheduler.runner import Scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def try_initial_connect(ble: BleManager, max_attempts: int = 5) -> bool:
    """Attempt initial BLE connection with exponential backoff.

    Returns True on success, False if all attempts fail.
    """
    for att in range(max_attempts):
        try:
            await ble.connect()
            return True
        except Exception as exc:
            logger.warning("BLE connect attempt %d/%d failed: %s", att + 1, max_attempts, exc)
            await asyncio.sleep(2**att)
    logger.warning("All %d initial connection attempts exhausted; relying on auto-reconnect", max_attempts)
    return False


async def main():
    cfg = Config()
    db = Database(cfg.db_path)
    await db.initialize()
    ble = BleManager(address=cfg.bedjet_address)
    connected = await try_initial_connect(ble)
    await ble.start_auto_reconnect()
    sched = Scheduler(ble, db)
    if connected:
        await sched.start()
    else:
        ble.on_connect = lambda: asyncio.ensure_future(sched.start())

    app = create_app(ble_manager=ble, db=db)
    app.state.scheduler = sched

    # mDNS
    zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    info = ServiceInfo(
        "_bedjet._tcp.local.",
        "BedJet Hub._bedjet._tcp.local.",
        port=cfg.hub_port,
        properties={"board": "bedjet-hub"},
        server="bedjet-hub.local.",
    )
    await zc.async_register_service(info)

    server = uvicorn.Server(uvicorn.Config(app, host=cfg.hub_host, port=cfg.hub_port, log_level="info"))
    logger.info(f"Starting on {cfg.hub_host}:{cfg.hub_port}")
    await server.serve()

    await zc.async_unregister_service(info)
    await zc.async_close()

    await sched.stop()
    await ble.disconnect()
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
