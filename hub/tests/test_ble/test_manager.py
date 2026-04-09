import asyncio
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bedjet_hub.ble.const import OperatingMode
from bedjet_hub.ble.manager import BleManager
from bedjet_hub.ble.state import DeviceState


@pytest.fixture
def mgr():
    return BleManager(address="AA:BB")


def test_init(mgr):
    assert mgr.get_state().mode == OperatingMode.STANDBY
    assert not mgr.is_connected


def test_meta(mgr):
    assert mgr.get_metadata().address == "AA:BB"


async def test_sub(mgr):
    r = []
    unsub = mgr.subscribe(lambda s: r.append(s))
    mgr._notify_subscribers(DeviceState(fan_speed_percent=50))
    assert len(r) == 1
    unsub()


async def test_unsub(mgr):
    r = []
    unsub = mgr.subscribe(lambda s: r.append(s))
    unsub()
    mgr._notify_subscribers(DeviceState())
    assert len(r) == 0


async def test_queue(mgr):
    o = []

    async def tw(cmd):
        o.append(cmd)

    mgr._write_command = tw
    mgr._connected = True
    mgr._client = MagicMock()
    await mgr._command_queue.put(bytes([1, 3]))
    await mgr._process_command_queue_once()
    assert len(o) >= 1


async def test_error(mgr):
    async def fw(cmd):
        raise Exception("fail")

    mgr._write_command = fw
    mgr._connected = True
    mgr._client = MagicMock()
    await mgr._command_queue.put(bytes([1, 3]))
    await mgr._process_command_queue_once()


def test_backoff(mgr):
    ds = [mgr._compute_reconnect_delay(i) for i in range(6)]
    assert ds[0] == 2
    assert ds[1] == 4
    assert ds[4] == 30
    assert ds[5] == 30


def test_activity(mgr):
    mgr._last_activity = datetime.now(UTC) - timedelta(seconds=59)
    mgr.reset_activity_timer()
    assert (datetime.now(UTC) - mgr._last_activity).total_seconds() < 1


async def test_connect_cleans_up_client_on_failure(mgr):
    """connect() must reset _client to None when BleakClient.connect() raises,
    so the next retry starts with a clean slate."""
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock(side_effect=OSError("BLE timeout"))

    with patch("bleak.BleakClient", return_value=mock_client):
        with pytest.raises(OSError, match="BLE timeout"):
            await mgr.connect()

    assert mgr._client is None
    assert not mgr.is_connected


async def test_connect_cleans_up_client_on_notify_failure(mgr):
    """If start_notify() fails after a successful low-level connect,
    the client should be disconnected and cleaned up."""
    mock_client = AsyncMock()
    mock_client.connect = AsyncMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock(side_effect=OSError("notify failed"))
    mock_client.disconnect = AsyncMock()

    with patch("bleak.BleakClient", return_value=mock_client):
        with pytest.raises(OSError, match="notify failed"):
            await mgr.connect()

    mock_client.disconnect.assert_awaited_once()
    assert mgr._client is None
    assert not mgr.is_connected


async def test_reconnect_loop_logs_errors(mgr, caplog):
    """_reconnect_loop must log the exception from each failed connect() attempt."""
    call_count = 0

    async def failing_connect():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            mgr._shutdown = True
        raise ConnectionError("adapter busy")

    mgr.connect = failing_connect
    mgr._compute_reconnect_delay = lambda att: 0

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble.manager"):
        await mgr._reconnect_loop()

    assert any("adapter busy" in r.message for r in caplog.records)


async def test_reconnect_loop_succeeds_after_failures(mgr):
    """_reconnect_loop should keep retrying and eventually connect."""
    call_count = 0
    notified = []

    mgr.subscribe(lambda s: notified.append(s))
    mgr._compute_reconnect_delay = lambda att: 0

    async def flaky_connect():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise OSError("busy")
        mgr._connected = True

    mgr.connect = flaky_connect

    async def stop_after_connected():
        while not mgr._connected:
            await asyncio.sleep(0)
        mgr._shutdown = True

    await asyncio.gather(mgr._reconnect_loop(), stop_after_connected())

    assert mgr.is_connected
    assert len(notified) >= 1


async def test_reconnect_loop_fires_on_connect_callback(mgr):
    """When _reconnect_loop establishes a connection, it must invoke the
    on_connect callback so the scheduler can be started lazily."""
    connected_events = []

    mgr.on_connect = lambda: connected_events.append(True)
    mgr._compute_reconnect_delay = lambda att: 0

    call_count = 0

    async def eventually_connect():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise OSError("busy")
        mgr._connected = True

    mgr.connect = eventually_connect

    async def stop_after_connected():
        while not mgr._connected:
            await asyncio.sleep(0)
        mgr._shutdown = True

    await asyncio.gather(mgr._reconnect_loop(), stop_after_connected())

    assert len(connected_events) == 1
