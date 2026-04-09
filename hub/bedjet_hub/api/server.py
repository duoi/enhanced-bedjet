"""FastAPI application factory for the BedJet Hub."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Config


def create_app(ble_manager=None, db=None):
    """Create and configure the FastAPI application.

    Registers device, program, preference, and WebSocket routers.
    CORS is locked down by default to local origins (port 8678, 5173).
    Configure the CORS_ORIGINS environment variable for network access.
    """
    app = FastAPI(title="BedJet Hub", version="0.2.1")
    cfg = Config()
    
    if "*" in cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    from .routes_device import create_device_router
    from .routes_preferences import create_preferences_router
    from .routes_programs import create_programs_router
    from .websocket import create_websocket_router

    app.include_router(create_device_router(ble_manager), prefix="/api")
    app.include_router(create_programs_router(db), prefix="/api")
    app.include_router(create_preferences_router(db), prefix="/api")
    app.include_router(create_websocket_router(ble_manager, db))
    return app
