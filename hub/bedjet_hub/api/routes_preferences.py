"""REST routes for user preferences (temp unit, default fan speed, etc.)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel


class PreferencesUpdate(BaseModel):
    temperatureUnit: str | None = None
    defaultFanSpeedPercent: int | None = None
    autoSyncClock: bool | None = None


def create_preferences_router(db):
    """Build an APIRouter with GET/PUT endpoints for user preferences."""
    r = APIRouter()

    @r.get("/preferences")
    async def get_preferences():
        return await db.get_preferences()

    @r.put("/preferences")
    async def update_preferences(req: PreferencesUpdate):
        u = {}
        if req.temperatureUnit is not None:
            u["temperatureUnit"] = req.temperatureUnit
        if req.defaultFanSpeedPercent is not None:
            u["defaultFanSpeedPercent"] = req.defaultFanSpeedPercent
        if req.autoSyncClock is not None:
            u["autoSyncClock"] = req.autoSyncClock
        return await db.update_preferences(u)

    return r
