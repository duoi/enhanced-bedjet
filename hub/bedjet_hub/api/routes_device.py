"""REST routes for direct device control (mode, fan, temperature, etc.)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from bedjet_hub.ble.const import OperatingMode


class ModeRequest(BaseModel):
    mode: str


class FanRequest(BaseModel):
    percent: int = Field(ge=5, le=100)


class TemperatureRequest(BaseModel):
    celsius: float


class LedRequest(BaseModel):
    enabled: bool


class MuteRequest(BaseModel):
    muted: bool


class RuntimeRequest(BaseModel):
    hours: int = Field(ge=0)
    minutes: int = Field(ge=0, le=59)


MODE_MAP = {
    "standby": OperatingMode.STANDBY,
    "heat": OperatingMode.HEAT,
    "turbo": OperatingMode.TURBO,
    "extended_heat": OperatingMode.EXTENDED_HEAT,
    "cool": OperatingMode.COOL,
    "dry": OperatingMode.DRY,
}


def serialize_state(s):
    """Convert a DeviceState dataclass to a JSON-serializable dict."""
    return {
        "mode": s.mode.name.lower(),
        "currentTemperatureC": s.current_temperature_c,
        "targetTemperatureC": s.target_temperature_c,
        "ambientTemperatureC": s.ambient_temperature_c,
        "fanSpeedPercent": s.app_fan_speed_percent,
        "runtimeRemainingSeconds": s.runtime_remaining_seconds,
        "runEndTime": s.run_end_time.isoformat() if s.run_end_time else None,
        "maximumRuntimeSeconds": s.maximum_runtime_seconds,
        "turboTimeSeconds": s.turbo_time_seconds,
        "minTemperatureC": s.min_temperature_c,
        "maxTemperatureC": s.max_temperature_c,
        "ledEnabled": s.led_enabled,
        "beepsMuted": s.beeps_muted,
        "dualZone": s.dual_zone,
        "unitsSetup": s.units_setup,
        "connectionTestPassed": s.connection_test_passed,
        "bioSequenceStep": s.bio_sequence_step,
        "notification": s.notification.name.lower() if s.notification else "none",
        "shutdownReason": s.shutdown_reason,
        "updatePhase": s.update_phase,
    }


def serialize_metadata(m):
    """Convert a DeviceMetadata dataclass to a JSON-serializable dict."""
    return {
        "address": m.address,
        "name": m.name,
        "model": m.model,
        "firmwareVersion": m.firmware_version,
        "memoryNames": m.memory_names,
        "biorhythmNames": m.biorhythm_names,
    }


def create_device_router(ble):
    """Build an APIRouter with endpoints for direct BedJet device control."""
    r = APIRouter()

    @r.get("/device")
    async def get_device():
        return {
            "connected": ble.is_connected,
            "metadata": serialize_metadata(ble.get_metadata()),
            "state": serialize_state(ble.get_state()),
        }

    @r.post("/device/mode")
    async def set_mode(req: ModeRequest):
        mode = MODE_MAP.get(req.mode)
        if mode is None:
            raise HTTPException(422, f"Invalid mode: {req.mode}")
        try:
            await ble.set_mode(mode)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/fan")
    async def set_fan(req: FanRequest):
        try:
            await ble.set_fan_speed(req.percent)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/temperature")
    async def set_temperature(req: TemperatureRequest):
        try:
            await ble.set_temperature(req.celsius)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/led")
    async def set_led(req: LedRequest):
        try:
            await ble.set_led(req.enabled)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/mute")
    async def set_mute(req: MuteRequest):
        try:
            await ble.set_muted(req.muted)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/clock/sync")
    async def sync_clock():
        try:
            await ble.sync_clock()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/runtime")
    async def set_runtime(req: RuntimeRequest):
        try:
            await ble.set_runtime(req.hours, req.minutes)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/memory/{slot}")
    async def activate_memory(slot: int):
        if slot not in (1, 2, 3):
            raise HTTPException(422, "Slot must be 1,2,3")
        try:
            await ble.activate_memory(slot)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @r.post("/device/biorhythm/{slot}")
    async def activate_biorhythm(slot: int):
        if slot not in (1, 2, 3):
            raise HTTPException(422, "Slot must be 1,2,3")
        try:
            await ble.activate_biorhythm(slot)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    return r
