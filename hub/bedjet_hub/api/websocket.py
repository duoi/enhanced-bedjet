"""WebSocket endpoint for real-time device state push to clients."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def _build_state(s, c, db):
    """Assemble a full state message including active program info."""
    active = await db.get_active_sequence()
    ap = None
    if active:
        p = await db.get_program(active["program_id"])
        if p:
            ap = {
                "programId": active["program_id"],
                "programName": p["name"],
                "startTime": active["start_time"],
                "currentStepIndex": active["current_step_index"],
                "startedAt": active["started_at"],
                "totalSteps": len(p["steps"]),
            }

    return {
        "type": "state",
        "connected": c,
        "state": {
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
        },
        "activeProgram": ap,
    }


def create_websocket_router(ble, db):
    """Build a router with a ``/ws`` WebSocket that streams device state."""
    r = APIRouter()

    @r.websocket("/ws")
    async def ws(ws: WebSocket):
        await ws.accept()
        init_state = await _build_state(ble.get_state(), ble.is_connected, db)
        await ws.send_json(init_state)
        q = asyncio.Queue()

        def oc(s):
            try:
                q.put_nowait(s)
            except Exception:
                pass

        unsub = ble.subscribe(oc)
        try:
            while True:
                try:
                    s = await asyncio.wait_for(q.get(), timeout=30.0)
                    state_msg = await _build_state(s, ble.is_connected, db)
                    await ws.send_json(state_msg)
                except TimeoutError:
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        break
        except WebSocketDisconnect:
            pass
        finally:
            unsub()

    return r
