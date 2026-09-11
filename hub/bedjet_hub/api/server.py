"""FastAPI application factory for the BedJet Hub."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..auth import AuthMiddleware
from ..config import AuthConfig, Config

logger = logging.getLogger(__name__)


def create_app(ble_manager=None, db=None):
    """Create and configure the FastAPI application.

    Registers device, program, preference, and WebSocket routers.

    CORS is locked down by default to local origins (port 8678, 5173);
    configure the CORS_ORIGINS environment variable for network access.

    Authentication is optional and configured through the environment: set
    HUB_API_TOKEN for a shared bearer token, and/or CF_ACCESS_TEAM_DOMAIN with
    CF_ACCESS_AUD to accept identity tokens from Cloudflare Access. With neither
    set the API is unauthenticated, which is only appropriate on a trusted LAN.
    """
    app = FastAPI(title="BedJet Hub", version="0.4.0")
    cfg = Config()
    auth_config = AuthConfig.from_env()

    if auth_config.enabled:
        # Registered before CORSMiddleware so that CORS stays the outermost layer
        # and keeps answering preflight requests, which carry no credentials.
        app.add_middleware(AuthMiddleware, config=auth_config)
    else:
        logger.warning(
            "API is unauthenticated: neither HUB_API_TOKEN nor CF_ACCESS_TEAM_DOMAIN/"
            "CF_ACCESS_AUD is set. Anyone who can reach this port can control the device."
        )

    if "*" in cfg.cors_origins:
        if auth_config.enabled:
            logger.warning(
                "CORS_ORIGINS is set to '*', which defeats CSRF protection: any website "
                "the user visits can issue commands to this API. List explicit origins instead."
            )
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
