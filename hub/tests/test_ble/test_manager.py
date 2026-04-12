import asyncio
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice

from bedjet_hub.ble.const import BEDJET3_STATUS_UUID, OperatingMode
from bedjet_hub.ble.manager import BleManager
from bedjet_hub.ble.state import DeviceState


@pytest.fixture
def mgr():
    return BleManager(address="AA:BB")


@pytest.fixture
def ble_device() -> BLEDevice:
    """A minimal BLEDevice for use with establish_connection."""
    return BLEDevice(address="AA:BB", name="BedJet", details={})


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


def test_activity(mgr):
    mgr._last_activity = datetime.now(UTC) - timedelta(seconds=59)
    mgr.reset_activity_timer()
    assert (datetime.now(UTC) - mgr._last_activity).total_seconds() < 1


# ---------------------------------------------------------------------------
# connect() via establish_connection + BleakClientWithServiceCache
# ---------------------------------------------------------------------------


async def test_connect_calls_establish_connection(mgr, ble_device):
    """connect() must delegate to establish_connection with
    BleakClientWithServiceCache, not raw BleakClient."""
    mock_client = AsyncMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client) as mock_ec,
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
        patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
    ):
        await mgr.connect()

    mock_ec.assert_awaited_once()
    call_args = mock_ec.call_args
    from bleak_retry_connector import BleakClientWithServiceCache

    assert call_args[0][0] is BleakClientWithServiceCache
    assert call_args[0][1] is ble_device


async def test_connect_passes_disconnected_callback(mgr, ble_device):
    """connect() must pass a disconnected_callback to establish_connection
    so the manager knows when the link drops."""
    mock_client = AsyncMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client) as mock_ec,
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
        patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
    ):
        await mgr.connect()

    kwargs = mock_ec.call_args.kwargs
    assert "disconnected_callback" in kwargs
    assert callable(kwargs["disconnected_callback"])


async def test_connect_cleans_up_on_establish_connection_failure(mgr, ble_device):
    """When establish_connection raises, _client must stay None."""
    from bleak_retry_connector import BleakNotFoundError

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, side_effect=BleakNotFoundError()),
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
    ):
        with pytest.raises(BleakNotFoundError):
            await mgr.connect()

    assert mgr._client is None
    assert not mgr.is_connected


async def test_connect_cleans_up_client_on_notify_failure(mgr, ble_device):
    """If start_notify() fails after establish_connection succeeds,
    the client should be disconnected and cleaned up."""
    mock_client = AsyncMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock(side_effect=OSError("notify failed"))
    mock_client.disconnect = AsyncMock()

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client),
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
    ):
        with pytest.raises(OSError, match="notify failed"):
            await mgr.connect()

    mock_client.disconnect.assert_awaited_once()
    assert mgr._client is None
    assert not mgr.is_connected


async def test_disconnected_callback_clears_connected(mgr, ble_device):
    """The disconnected_callback passed to establish_connection must set
    _connected = False so the reconnect loop re-enters."""
    mock_client = AsyncMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()

    captured_cb = None

    async def capture_establish_connection(*args, **kwargs):
        nonlocal captured_cb
        captured_cb = kwargs.get("disconnected_callback")
        return mock_client

    with (
        patch("bedjet_hub.ble.manager.establish_connection", side_effect=capture_establish_connection),
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
        patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
    ):
        await mgr.connect()

    assert mgr.is_connected
    assert captured_cb is not None

    captured_cb(mock_client)
    assert not mgr.is_connected


# ---------------------------------------------------------------------------
# _resolve_ble_device: scan returning BLEDevice
# ---------------------------------------------------------------------------


async def test_resolve_ble_device_from_address(mgr):
    """When address is set, _resolve_ble_device must use
    BleakScanner.find_device_by_address to get a BLEDevice."""
    expected = BLEDevice(address="AA:BB", name="BedJet", details={})

    with patch("bedjet_hub.ble.manager.BleakScanner") as mock_scanner_cls:
        mock_scanner_cls.find_device_by_address = AsyncMock(return_value=expected)
        result = await mgr._resolve_ble_device()

    assert result is expected


async def test_resolve_ble_device_scan_when_no_address():
    """When no address is configured, _resolve_ble_device must scan
    and return the first BLEDevice whose name contains 'bedjet'."""
    mgr = BleManager(address="")
    bedjet_dev = BLEDevice(address="CC:DD", name="BEDJET3", details={})

    with patch("bedjet_hub.ble.manager.BleakScanner") as mock_scanner_cls:
        mock_scanner_cls.discover = AsyncMock(return_value=[bedjet_dev])
        result = await mgr._resolve_ble_device()

    assert result is bedjet_dev
    assert mgr._address == "CC:DD"


async def test_resolve_ble_device_raises_when_not_found(mgr):
    """_resolve_ble_device must raise RuntimeError when the device
    cannot be found by address."""
    with patch("bedjet_hub.ble.manager.BleakScanner") as mock_scanner_cls:
        mock_scanner_cls.find_device_by_address = AsyncMock(return_value=None)
        with pytest.raises(RuntimeError, match="not found"):
            await mgr._resolve_ble_device()


# ---------------------------------------------------------------------------
# Typed exception handling in reconnect loop
# ---------------------------------------------------------------------------


async def test_reconnect_loop_logs_not_found_error(mgr, caplog):
    """_reconnect_loop must log BleakNotFoundError distinctly."""
    from bleak_retry_connector import BleakNotFoundError

    call_count = 0

    async def failing_connect():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            mgr._shutdown = True
        raise BleakNotFoundError()

    mgr.connect = failing_connect
    mgr._reconnect_delay = 0

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble.manager"):
        await mgr._reconnect_loop()

    assert any("not found" in r.message.lower() for r in caplog.records)


async def test_reconnect_loop_logs_generic_errors(mgr, caplog):
    """_reconnect_loop must still log generic exceptions."""
    call_count = 0

    async def failing_connect():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            mgr._shutdown = True
        raise ConnectionError("adapter busy")

    mgr.connect = failing_connect
    mgr._reconnect_delay = 0

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble.manager"):
        await mgr._reconnect_loop()

    assert any("adapter busy" in r.message for r in caplog.records)


async def test_reconnect_loop_succeeds_after_failures(mgr):
    """_reconnect_loop should keep retrying and eventually connect."""
    call_count = 0
    notified = []

    mgr.subscribe(lambda s: notified.append(s))
    mgr._reconnect_delay = 0

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
    mgr._reconnect_delay = 0

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
