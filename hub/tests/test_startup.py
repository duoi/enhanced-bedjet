import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

import bedjet_hub.ble_daemon as startup_mod


async def test_startup_connect_success(caplog):
    """try_initial_connect returns True when connect() succeeds.

    With establish_connection handling internal retries, the startup
    function is a single-call wrapper.
    """
    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock()

    result = await startup_mod.try_initial_connect(mock_ble)

    assert result is True
    mock_ble.connect.assert_awaited_once()


async def test_startup_connect_logs_failure(caplog):
    """try_initial_connect returns False and logs when connect() raises."""
    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock(side_effect=OSError("Device not found"))

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble_daemon"):
        result = await startup_mod.try_initial_connect(mock_ble)

    assert result is False
    assert any("Device not found" in r.message for r in caplog.records)


async def test_startup_connect_handles_typed_exceptions(caplog):
    """try_initial_connect should handle bleak-retry-connector exceptions."""
    from bleak_retry_connector import BleakNotFoundError

    mock_ble = AsyncMock()
    mock_ble.connect = AsyncMock(side_effect=BleakNotFoundError())

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble_daemon"):
        result = await startup_mod.try_initial_connect(mock_ble)

    assert result is False
    assert any("Initial BLE connection failed" in r.message for r in caplog.records)


# --------------------------------------------------------------------------- #
# Stale-data watchdog
# --------------------------------------------------------------------------- #


def _watchdog_ble(*, connected=True, stale=True, side_effect=None):
    ble = MagicMock()
    ble.is_connected = connected
    if side_effect is not None:
        ble.check_stale_data = AsyncMock(side_effect=side_effect)
    else:
        ble.check_stale_data = AsyncMock(return_value=stale)
    return ble


async def test_watchdog_fires_when_notifications_go_stale():
    """The watchdog reports staleness and then stops."""
    ble = _watchdog_ble(stale=True)
    fired = []

    await asyncio.wait_for(
        startup_mod.stale_data_watchdog(ble, lambda: fired.append(True), interval_seconds=0.01),
        timeout=5,
    )

    assert fired == [True]


async def test_watchdog_keeps_polling_while_data_is_fresh():
    ble = _watchdog_ble(stale=False)
    fired = []

    task = asyncio.create_task(
        startup_mod.stale_data_watchdog(ble, lambda: fired.append(True), interval_seconds=0.01)
    )
    await asyncio.sleep(0.08)
    task.cancel()

    assert fired == []
    assert ble.check_stale_data.await_count >= 2


async def test_watchdog_ignores_a_disconnected_device():
    """A disconnected link reports no notifications, which must not look stale."""
    ble = _watchdog_ble(connected=False, stale=True)
    fired = []

    task = asyncio.create_task(
        startup_mod.stale_data_watchdog(ble, lambda: fired.append(True), interval_seconds=0.01)
    )
    await asyncio.sleep(0.08)
    task.cancel()

    assert fired == []
    assert ble.check_stale_data.await_count == 0


async def test_watchdog_survives_a_failing_check(caplog):
    """One error must not silently kill the last line of defence."""
    ble = _watchdog_ble(side_effect=[RuntimeError("d-bus hiccup"), True])
    fired = []

    with caplog.at_level(logging.ERROR, logger="bedjet_hub.ble_daemon"):
        await asyncio.wait_for(
            startup_mod.stale_data_watchdog(
                ble, lambda: fired.append(True), interval_seconds=0.01
            ),
            timeout=5,
        )

    assert fired == [True]
    assert any("continuing to watch" in r.message for r in caplog.records)


async def test_watchdog_stops_promptly_when_cancelled():
    """Shutdown must not wait a full interval for the sleeping watchdog."""
    ble = _watchdog_ble(stale=False)

    task = asyncio.create_task(
        startup_mod.stale_data_watchdog(ble, lambda: None, interval_seconds=30)
    )
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
