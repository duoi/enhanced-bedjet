import asyncio
import os
import tempfile
from datetime import UTC
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


def test_create(client):
    r = client.post(
        "/api/programs",
        json={
            "name": "Night",
            "steps": [{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}],
        },
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Night"
    assert len(r.json()["steps"]) == 1


def test_list(client):
    client.post("/api/programs", json={"name": "A", "steps": []})
    client.post("/api/programs", json={"name": "B", "steps": []})
    assert len(client.get("/api/programs").json()) == 2


def test_get(client):
    c = client.post("/api/programs", json={"name": "T", "steps": []}).json()
    assert client.get(f"/api/programs/{c['id']}").json()["name"] == "T"


def test_404(client):
    assert client.get("/api/programs/nope").status_code == 404


def test_update(client):
    c = client.post("/api/programs", json={"name": "Old", "steps": []}).json()
    assert client.put(f"/api/programs/{c['id']}", json={"name": "New"}).json()["name"] == "New"


def test_delete(client):
    c = client.post("/api/programs", json={"name": "Del", "steps": []}).json()
    assert client.delete(f"/api/programs/{c['id']}").json()["ok"]
    assert client.get(f"/api/programs/{c['id']}").status_code == 404


def test_activate(client):
    p = client.post(
        "/api/programs",
        json={
            "name": "T",
            "steps": [{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}],
        },
    ).json()
    from datetime import datetime

    r = client.post(f"/api/programs/{p['id']}/activate", json={"startTime": datetime.now(UTC).isoformat()})
    assert r.json()["ok"]


def test_stop(client):
    assert client.post("/api/programs/stop").json()["ok"]


def test_active(client):
    assert client.get("/api/programs/active").json() is None

def test_create_with_schedule(client):
    r = client.post(
        "/api/programs",
        json={
            "name": "Scheduled",
            "startTime": "22:00",
            "days": [1, 3, 5],
            "steps": [{"mode": "heat", "temperatureC": 30, "durationMinutes": 60}],
        },
    )
    assert r.status_code == 200
    p = r.json()
    assert p["name"] == "Scheduled"

    r2 = client.get(f"/api/programs/{p['id']}")
    assert r2.status_code == 200
    p2 = r2.json()
    assert p2["startTime"] == "22:00"
    assert p2["days"] == [1, 3, 5]
