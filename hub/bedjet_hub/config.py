"""Hub configuration loaded from environment variables."""

import os


class Config:
    """Runtime configuration sourced from environment variables.

    Attributes:
        bedjet_address: BLE MAC address of the BedJet device. Empty string
            triggers auto-scan.
        hub_host: Network interface to bind the HTTP/WS server on.
        hub_port: TCP port for the hub server.
        db_path: Filesystem path for the SQLite database.
    """

    bedjet_address: str = os.environ.get("BEDJET_ADDRESS", "")
    hub_host: str = os.environ.get("HUB_HOST", "0.0.0.0")
    hub_port: int = int(os.environ.get("HUB_PORT", "8265"))
    db_path: str = os.environ.get("DB_PATH", "data/bedjet.db")
    cors_origins: list[str] = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:8678,http://localhost:5173").split(",")
        if o.strip()
    ]
