import asyncio
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bedjet_hub.api.server import create_app
from bedjet_hub.db.database import Database


@pytest.fixture
def client():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(p)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(db.initialize())
    app = create_app(ble_manager=MagicMock(), db=db)
    with TestClient(app) as c:
        yield c
    loop.run_until_complete(db.close())
    os.unlink(p)


def test_defaults(client):
    d = client.get("/api/preferences").json()
    assert d["temperatureUnit"] == "celsius"
    assert d["defaultFanSpeedPercent"] == 50


def test_update(client):
    r = client.put("/api/preferences", json={"temperatureUnit": "fahrenheit", "defaultFanSpeedPercent": 75}).json()
    assert r["temperatureUnit"] == "fahrenheit"


def test_partial(client):
    client.put("/api/preferences", json={"defaultFanSpeedPercent": 80})
    assert client.get("/api/preferences").json()["defaultFanSpeedPercent"] == 80
