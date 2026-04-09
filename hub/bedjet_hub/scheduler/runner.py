"""Biorhythm program scheduler: activates, sequences, and resumes programs.

Programs are multi-step sequences where each step sets a mode, temperature,
fan speed, and duration. The scheduler handles late starts by computing the
correct step offset and remaining time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from bedjet_hub.ble.const import OperatingMode

logger = logging.getLogger(__name__)
MODE_MAP = {
    "standby": OperatingMode.STANDBY,
    "heat": OperatingMode.HEAT,
    "turbo": OperatingMode.TURBO,
    "extended_heat": OperatingMode.EXTENDED_HEAT,
    "cool": OperatingMode.COOL,
    "dry": OperatingMode.DRY,
    "wait": OperatingMode.WAIT,
}


class Scheduler:
    """Executes biorhythm programs as timed BLE command sequences.

    Walks through program steps, setting mode/temp/fan on the device
    and scheduling async timers for step transitions. Supports resume
    after hub restart by persisting active sequence state in the DB.
    """

    def __init__(self, ble, db):
        self._ble = ble
        self._db = db
        self._timer_task = None
        self._poll_task = None
        self._shutdown = False
        self._last_polled_minute = None

    async def start(self):
        a = await self._db.get_active_sequence()
        if a:
            await self._resume(a)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._shutdown = True
        if self._timer_task:
            self._timer_task.cancel()
        if self._poll_task:
            self._poll_task.cancel()

    async def activate_program(self, program, start_time):
        now = datetime.now(UTC)
        delta = max(0, (now - start_time).total_seconds())
        steps = program["steps"]
        if not steps:
            raise ValueError("No steps")
        elapsed = delta
        csi = 0
        for i, s in enumerate(steps):
            ds = s["durationMinutes"] * 60
            if ds == 0:
                continue
            if elapsed < ds:
                csi = i
                rem = ds - elapsed
                break
            elapsed -= ds
        else:
            raise ValueError("Fully elapsed")
        step = steps[csi]
        await self._ble.set_mode(MODE_MAP.get(step["mode"], OperatingMode.STANDBY))
        if step.get("temperatureC") is not None:
            await self._ble.set_temperature(step["temperatureC"])
        if step.get("fanSpeedPercent") is not None:
            await self._ble.set_fan_speed(step["fanSpeedPercent"])
        rm = int(rem / 60)
        await self._ble.set_runtime(rm // 60, rm % 60)
        await self._db.set_active_sequence(
            program_id=program["id"],
            start_time=start_time.isoformat(),
            current_step_index=csi,
            started_at=now.isoformat(),
        )
        self._timer_task = asyncio.create_task(self._step_timer(program, csi, now + timedelta(seconds=rem)))

    async def stop_program(self):
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        await self._db.delete_active_sequence()

    async def _resume(self, active):
        p = await self._db.get_program(active["program_id"])
        if not p:
            await self._db.delete_active_sequence()
            return
        try:
            st = datetime.fromisoformat(active["start_time"].replace("Z", "+00:00"))
        except Exception:
            await self._db.delete_active_sequence()
            return
        await self.activate_program(p, st)

    async def _step_timer(self, program, idx, end_time):
        sl = (end_time - datetime.now(UTC)).total_seconds()
        if sl > 0:
            await asyncio.sleep(sl)
        if self._shutdown:
            return
        ni = idx + 1
        if ni >= len(program["steps"]):
            if self._ble.get_state().mode != OperatingMode.STANDBY:
                await self._ble.set_mode(OperatingMode.STANDBY)
            await self._db.delete_active_sequence()
            return
        ns = program["steps"][ni]
        await self._ble.set_mode(MODE_MAP.get(ns["mode"], OperatingMode.STANDBY))
        if ns.get("temperatureC") is not None:
            await self._ble.set_temperature(ns["temperatureC"])
        if ns.get("fanSpeedPercent") is not None:
            await self._ble.set_fan_speed(ns["fanSpeedPercent"])
        await self._ble.set_runtime(ns["durationMinutes"] // 60, ns["durationMinutes"] % 60)
        await self._db.update_active_sequence_step(ni)
        ne = datetime.now(UTC) + timedelta(seconds=ns["durationMinutes"] * 60)
        self._timer_task = asyncio.create_task(self._step_timer(program, ni, ne))

    async def _poll_loop(self):
        while not self._shutdown:
            try:
                await self._poll_schedules()
            except Exception as e:
                logger.error("Error polling schedules: %s", e)
            await asyncio.sleep(20)

    async def _poll_schedules(self, now=None):
        if now is None:
            now = datetime.now()
            
        current_minute = now.strftime("%H:%M")
        
        if self._last_polled_minute == current_minute:
            return
            
        weekday = now.weekday()
        programs = await self._db.list_programs()
        
        for p in programs:
            if not p.get("startTime") or not p.get("days"):
                continue
                
            if p["startTime"] == current_minute and weekday in p["days"]:
                active = await self._db.get_active_sequence()
                if active and active["program_id"] == p["id"]:
                    continue
                    
                logger.info("Schedule matched: Activating program %s", p["name"])
                if self._timer_task:
                    self._timer_task.cancel()
                    self._timer_task = None
                    
                self._last_polled_minute = current_minute
                
                # activate_program expects a UTC aware datetime
                st = now.astimezone(UTC) if now.tzinfo else datetime.now(UTC)
                try:
                    await self.activate_program(p, st)
                except Exception as e:
                    logger.error("Failed to scheduled-activate program %s: %s", p["id"], e)
                break
