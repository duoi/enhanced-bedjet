from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from bedjet_hub.api.server import create_app
from bedjet_hub.ble.const import OperatingMode
from bedjet_hub.ble.state import DeviceMetadata, DeviceState


@pytest.fixture
def client():
    import asyncio
    import os
    import tempfile

    from bedjet_hub.db.database import Database

    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(p)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(db.initialize())
    mb = MagicMock()
    mb.is_connected = True
    for m in [
        "set_mode",
        "set_fan_speed",
        "set_temperature",
        "set_led",
        "set_muted",
        "sync_clock",
        "set_runtime",
        "activate_memory",
        "activate_biorhythm",
    ]:
        setattr(mb, m, AsyncMock())
    mb.get_state.return_value = DeviceState(
        mode=OperatingMode.HEAT,
        current_temperature_c=36.5,
        target_temperature_c=38.0,
        ambient_temperature_c=22.0,
        fan_speed_percent=60,
        runtime_remaining_seconds=1800,
        maximum_runtime_seconds=14400,
        min_temperature_c=19.0,
        max_temperature_c=43.0,
        led_enabled=True,
        beeps_muted=False,
        dual_zone=False,
        units_setup=True,
        connection_test_passed=True,
    )
    mb.get_metadata.return_value = DeviceMetadata(
        address="AA:BB",
        name="BedJet",
        model="v3",
        firmware_version="1.2.3",
        memory_names=["Sleep", None, None],
        biorhythm_names=["Night", None, None],
    )
    app = create_app(ble_manager=mb, db=db)
    with TestClient(app) as c:
        yield c
    loop.run_until_complete(db.close())
    os.unlink(p)


def test_get_device(client):
    r = client.get("/api/device")
    assert r.status_code == 200
    d = r.json()
    assert d["connected"]
    assert d["state"]["mode"] == "heat"


def test_set_mode(client):
    assert client.post("/api/device/mode", json={"mode": "cool"}).json()["ok"]


def test_invalid_mode(client):
    assert client.post("/api/device/mode", json={"mode": "x"}).status_code == 422


def test_fan(client):
    assert client.post("/api/device/fan", json={"percent": 75}).json()["ok"]


def test_fan_range(client):
    assert client.post("/api/device/fan", json={"percent": 3}).status_code == 422


def test_temp(client):
    assert client.post("/api/device/temperature", json={"celsius": 30}).json()["ok"]


def test_led(client):
    assert client.post("/api/device/led", json={"enabled": True}).json()["ok"]


def test_mute(client):
    assert client.post("/api/device/mute", json={"muted": True}).json()["ok"]


def test_clock(client):
    assert client.post("/api/device/clock/sync").json()["ok"]


def test_runtime(client):
    assert client.post("/api/device/runtime", json={"hours": 2, "minutes": 30}).json()["ok"]


def test_memory(client):
    assert client.post("/api/device/memory/1").json()["ok"]


def test_memory_bad(client):
    assert client.post("/api/device/memory/5").status_code == 422


def test_biorhythm(client):
    assert client.post("/api/device/biorhythm/2").json()["ok"]
