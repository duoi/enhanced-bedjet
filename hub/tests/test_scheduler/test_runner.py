import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bedjet_hub.ble.const import OperatingMode
from bedjet_hub.ble.state import DeviceState
from bedjet_hub.db.database import Database
from bedjet_hub.scheduler.runner import Scheduler


@pytest.fixture
async def sched():
    fd, p = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(p)
    await db.initialize()
    ble = MagicMock()
    ble.set_mode = AsyncMock()
    ble.set_temperature = AsyncMock()
    ble.set_fan_speed = AsyncMock()
    ble.set_runtime = AsyncMock()
    ble.get_state.return_value = DeviceState(mode=OperatingMode.HEAT)
    s = Scheduler(ble=ble, db=db)
    yield s, db, ble
    await s.stop()
    await db.close()
    os.unlink(p)


async def test_immediate(sched):
    s, db, ble = sched
    p = await db.create_program(
        name="T", steps=[{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}]
    )
    await s.activate_program(p, datetime.now(UTC))
    ble.set_mode.assert_called_with(OperatingMode.HEAT)
    a = await db.get_active_sequence()
    assert a["current_step_index"] == 0


async def test_late(sched):
    s, db, ble = sched
    p = await db.create_program(
        name="T",
        steps=[
            {"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30},
            {"mode": "cool", "temperatureC": 22, "fanSpeedPercent": 40, "durationMinutes": 120},
        ],
    )
    await s.activate_program(p, datetime.now(UTC) - timedelta(minutes=45))
    ble.set_mode.assert_called_with(OperatingMode.COOL)


async def test_elapsed(sched):
    s, db, ble = sched
    p = await db.create_program(
        name="T", steps=[{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}]
    )
    with pytest.raises(ValueError):
        await s.activate_program(p, datetime.now(UTC) - timedelta(hours=2))


async def test_stop(sched):
    s, db, ble = sched
    p = await db.create_program(
        name="T", steps=[{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}]
    )
    await s.activate_program(p, datetime.now(UTC))
    await s.stop_program()
    assert await db.get_active_sequence() is None


async def test_resume(sched):
    s, db, ble = sched
    p = await db.create_program(
        name="T", steps=[{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}]
    )
    now = datetime.now(UTC).isoformat()
    await db.set_active_sequence(p["id"], now, 0, now)
    await s.start()
    ble.set_mode.assert_called_with(OperatingMode.HEAT)


async def test_polling_activates_scheduled_program(sched):
    s, db, ble = sched
    
    # Create a scheduled program for 22:00 on Wednesday (weekday 2)
    p = await db.create_program(
        name="Scheduled",
        steps=[{"mode": "heat", "temperatureC": 38, "fanSpeedPercent": 60, "durationMinutes": 30}],
        start_time_hhmm="22:00",
        days=[0, 2, 4]  # Mon, Wed, Fri
    )
    
    # Mock datetime to Wed 2026-04-15 22:00:00 UTC
    mock_now_match = datetime(2026, 4, 15, 22, 0, 0, tzinfo=UTC)
    
    # Run the poll method (which we will implement)
    await s._poll_schedules(now=mock_now_match)
    
    # Should have started the program
    ble.set_mode.assert_called_with(OperatingMode.HEAT)
    a = await db.get_active_sequence()
    assert a is not None
    assert a["program_id"] == p["id"]

    # Clear it
    await db.delete_active_sequence()
    ble.set_mode.reset_mock()

    # Test non-matching day (Tuesday)
    mock_now_wrong_day = datetime(2026, 4, 14, 22, 0, 0, tzinfo=UTC)
    await s._poll_schedules(now=mock_now_wrong_day)
    ble.set_mode.assert_not_called()

    # Test non-matching time (22:01)
    mock_now_wrong_time = datetime(2026, 4, 15, 22, 1, 0, tzinfo=UTC)
    await s._poll_schedules(now=mock_now_wrong_time)
    ble.set_mode.assert_not_called()
