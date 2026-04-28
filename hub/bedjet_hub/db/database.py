"""Async SQLite database for programs, preferences, and active sequence state."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import aiosqlite

DEFAULT_PREFS = {"temperatureUnit": "celsius", "defaultFanSpeedPercent": 50, "autoSyncClock": True}
SCHEMA = """
CREATE TABLE IF NOT EXISTS programs(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    start_time_hhmm TEXT,
    days TEXT
);
CREATE TABLE IF NOT EXISTS program_steps(
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    mode TEXT NOT NULL,
    temperature_c REAL,
    fan_speed_percent INTEGER,
    duration_minutes INTEGER NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS telemetry(
    timestamp TEXT PRIMARY KEY,
    mode TEXT,
    temperature_c REAL,
    fan_speed_percent INTEGER
);
CREATE TABLE IF NOT EXISTS active_sequence(
    id INTEGER PRIMARY KEY CHECK(id=1),
    program_id TEXT NOT NULL,
    start_time TEXT NOT NULL,
    current_step_index INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    FOREIGN KEY(program_id) REFERENCES programs(id)
);
"""

class Database:
    """Async SQLite wrapper for program storage, preferences, and scheduler state."""

    def __init__(self, path: str = "data/bedjet.db"):
        self._path = path
        self._db = None

    async def initialize(self):
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        try:
            await self._db.execute("ALTER TABLE programs ADD COLUMN start_time_hhmm TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await self._db.execute("ALTER TABLE programs ADD COLUMN days TEXT")
        except aiosqlite.OperationalError:
            pass
        c = await self._db.execute("SELECT COUNT(*)FROM preferences")
        r = await c.fetchone()
        if r[0] == 0:
            for k, v in DEFAULT_PREFS.items():
                await self._db.execute("INSERT INTO preferences(key,value)VALUES(?,?)", (k, json.dumps(v)))
            await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None

    async def create_program(self, name, steps=None, start_time_hhmm=None, days=None):
        pid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        await self._db.execute(
            "INSERT INTO programs(id,name,created_at,updated_at,start_time_hhmm,days)VALUES(?,?,?,?,?,?)",
            (pid, name, now, now, start_time_hhmm, json.dumps(days) if days is not None else None)
        )
        if steps:
            for i, s in enumerate(steps):
                sid = str(uuid.uuid4())
                await self._db.execute(
                    "INSERT INTO program_steps("
                    "id,program_id,position,mode,temperature_c,fan_speed_percent,duration_minutes"
                    ")VALUES(?,?,?,?,?,?,?)",
                    (sid, pid, i, s["mode"], s.get("temperatureC"), s.get("fanSpeedPercent"), s["durationMinutes"]),
                )
        await self._db.commit()
        return await self.get_program(pid)

    async def get_program(self, pid):
        c = await self._db.execute("SELECT*FROM programs WHERE id=?", (pid,))
        r = await c.fetchone()
        if not r:
            return None
        p = dict(r)
        p["steps"] = await self._get_steps(pid)
        return self._normalize_program(p)

    async def list_programs(self):
        c = await self._db.execute("SELECT*FROM programs ORDER BY created_at")
        ps = []
        for r in await c.fetchall():
            p = dict(r)
            p["steps"] = await self._get_steps(p["id"])
            ps.append(self._normalize_program(p))
        return ps

    async def update_program(self, pid, name=None, steps=None, start_time_hhmm=None, days=None):
        if not await self.get_program(pid):
            return None
        now = datetime.now(UTC).isoformat()
        if name:
            await self._db.execute("UPDATE programs SET name=?,updated_at=?WHERE id=?", (name, now, pid))
        if start_time_hhmm is not None:
            await self._db.execute("UPDATE programs SET start_time_hhmm=? WHERE id=?", (start_time_hhmm, pid))
        if days is not None:
            await self._db.execute("UPDATE programs SET days=? WHERE id=?", (json.dumps(days), pid))
        if steps is not None:
            await self._db.execute("DELETE FROM program_steps WHERE program_id=?", (pid,))
            for i, s in enumerate(steps):
                sid = str(uuid.uuid4())
                await self._db.execute(
                    "INSERT INTO program_steps("
                    "id,program_id,position,mode,temperature_c,fan_speed_percent,duration_minutes"
                    ")VALUES(?,?,?,?,?,?,?)",
                    (sid, pid, i, s["mode"], s.get("temperatureC"), s.get("fanSpeedPercent"), s["durationMinutes"]),
                )
        await self._db.execute("UPDATE programs SET updated_at=?WHERE id=?", (now, pid))
        await self._db.commit()
        return await self.get_program(pid)

    async def delete_program(self, pid):
        c = await self._db.execute("DELETE FROM programs WHERE id=?", (pid,))
        await self._db.commit()
        return c.rowcount > 0

    async def _get_steps(self, pid: str) -> list[dict]:
        """Fetch ordered steps for a given program ID."""
        c = await self._db.execute("SELECT*FROM program_steps WHERE program_id=?ORDER BY position", (pid,))
        return [
            {
                "position": r["position"],
                "mode": r["mode"],
                "temperatureC": r["temperature_c"],
                "fanSpeedPercent": r["fan_speed_percent"],
                "durationMinutes": r["duration_minutes"],
            }
            for r in await c.fetchall()
        ]

    def _normalize_program(self, p: dict) -> dict:
        """Map DB column names to camelCase API field names."""
        return {
            "id": p["id"],
            "name": p["name"],
            "steps": p.get("steps", []),
            "createdAt": p["created_at"],
            "updatedAt": p["updated_at"],
            "startTime": p.get("start_time_hhmm"),
            "days": json.loads(p["days"]) if p.get("days") else [],
        }

    async def get_preferences(self):
        c = await self._db.execute("SELECT key,value FROM preferences")
        p = dict(DEFAULT_PREFS)
        for r in await c.fetchall():
            p[r["key"]] = json.loads(r["value"])
        return p

    async def update_preferences(self, prefs):
        for k, v in prefs.items():
            await self._db.execute("INSERT OR REPLACE INTO preferences(key,value)VALUES(?,?)", (k, json.dumps(v)))
        await self._db.commit()
        return await self.get_preferences()

    async def get_active_sequence(self):
        c = await self._db.execute("SELECT*FROM active_sequence WHERE id=1")
        r = await c.fetchone()
        if not r:
            return None
        return {
            "program_id": r["program_id"],
            "start_time": r["start_time"],
            "current_step_index": r["current_step_index"],
            "started_at": r["started_at"],
        }

    async def set_active_sequence(self, program_id, start_time, current_step_index, started_at):
        await self._db.execute("DELETE FROM active_sequence")
        await self._db.execute(
            "INSERT INTO active_sequence(id,program_id,start_time,current_step_index,started_at)VALUES(1,?,?,?,?)",
            (program_id, start_time, current_step_index, started_at),
        )
        await self._db.commit()

    async def update_active_sequence_step(self, idx):
        await self._db.execute("UPDATE active_sequence SET current_step_index=?WHERE id=1", (idx,))
        await self._db.commit()

    async def delete_active_sequence(self):
        await self._db.execute("DELETE FROM active_sequence")
        await self._db.commit()

    async def add_telemetry(self, timestamp: str, mode: str, temp_c: float, fan: int):
        await self._db.execute(
            "INSERT INTO telemetry(timestamp,mode,temperature_c,fan_speed_percent)VALUES(?,?,?,?)",
            (timestamp, mode, temp_c, fan)
        )
        await self._db.commit()

    async def get_telemetry(self, limit: int = 100):
        c = await self._db.execute("SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT ?", (limit,))
        return [dict(r) for r in await c.fetchall()]
