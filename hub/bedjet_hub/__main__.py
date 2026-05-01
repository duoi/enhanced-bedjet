import asyncio
import logging

import uvicorn
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from .api.server import create_app
from .ble.ipc_client import BleProxyClient
from .config import Config
from .db.database import Database
from .scheduler.runner import Scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)



async def telemetry_loop(ble: BleProxyClient, db: Database):
    import asyncio
    from datetime import UTC, datetime
    while True:
        try:
            if getattr(ble, 'is_connected', False):
                state = ble.get_state() if callable(getattr(ble, 'get_state', None)) else getattr(
                    ble, 'get_state', None)
                if state:
                    mode_str = str(getattr(state, "mode", "unknown")).lower()
                    if mode_str not in ["0", "standby", "off"]:
                        await db.add_telemetry(
                            timestamp=datetime.now(UTC).isoformat(),
                            mode=getattr(state, "mode", "unknown"),
                            temp_c=getattr(state, "current_temperature_c", getattr(state, "temperatureC", 0.0)),
                            fan=getattr(state, "fan_speed_percent", getattr(state, "fanSpeedPercent", 0))
                        )
        except Exception as e:
            import traceback
            logger.error(f"Telemetry error: {e}\n{traceback.format_exc()}")
        await asyncio.sleep(300)  # 5 minutes

async def try_initial_connect(ble):
    pass



async def main():
    cfg = Config()
    db = Database(cfg.db_path)
    await db.initialize()

    # Initialize the Proxy Client
    ble = BleProxyClient()
    await ble.connect()

    sched = Scheduler(ble, db)
    await sched.start()

    app = create_app(ble_manager=ble, db=db)
    app.state.scheduler = sched
    asyncio.create_task(telemetry_loop(ble, db))


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
