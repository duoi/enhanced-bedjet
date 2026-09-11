import asyncio
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak.backends.device import BLEDevice

from bedjet_hub.ble import protocol_v3
from bedjet_hub.ble.const import BiodataRequestType, ButtonCode, OperatingMode
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


# ---------------------------------------------------------------------------
# Runtime preservation across mode changes
#
# Firmware resets the runtime to the mode default on every mode change.
# These tests pin the hub-side rule: only an explicit set_runtime() may
# change the timer; a mode change while running re-applies the remaining
# time so the run is never extended.
# ---------------------------------------------------------------------------


def _armed(mgr, mode=OperatingMode.HEAT):
    mgr._connected = True
    mgr._client = MagicMock()
    mgr._state.mode = mode
    mgr._enqueue_command = AsyncMock()
    mgr._wait_for_mode_change = AsyncMock()
    return mgr


def _sent(mgr):
    return [c.args[0] for c in mgr._enqueue_command.await_args_list]


_FIXED_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


class _FrozenDateTime:
    """datetime stub so remaining-time math is deterministic in tests."""

    @staticmethod
    def now(tz=None):
        return _FIXED_NOW


def _freeze(monkeypatch):
    monkeypatch.setattr("bedjet_hub.ble.manager.datetime", _FrozenDateTime)


async def test_set_mode_preserves_running_timer(mgr, monkeypatch):
    """Mode change while running must re-apply the remaining runtime."""
    _armed(mgr)
    _freeze(monkeypatch)
    mgr._state.run_end_time = _FIXED_NOW + timedelta(seconds=3600)
    monkeypatch.setattr("bedjet_hub.ble.manager.asyncio.sleep", AsyncMock())

    await mgr.set_mode(OperatingMode.COOL)

    sent = _sent(mgr)
    assert sent[0] == protocol_v3.encode_button(ButtonCode.COOL)
    assert sent[-1] == protocol_v3.encode_set_runtime(1, 0)


async def test_set_mode_preserves_timer_on_same_mode_resend(mgr, monkeypatch):
    """Re-sending the already-active mode must not extend the timer."""
    _armed(mgr, OperatingMode.EXTENDED_HEAT)
    _freeze(monkeypatch)
    mgr._state.run_end_time = _FIXED_NOW + timedelta(seconds=7200)
    monkeypatch.setattr("bedjet_hub.ble.manager.asyncio.sleep", AsyncMock())

    await mgr.set_mode(OperatingMode.EXTENDED_HEAT)

    assert _sent(mgr)[-1] == protocol_v3.encode_set_runtime(2, 0)


async def test_set_mode_from_standby_keeps_default_runtime(mgr):
    """Starting a mode while off must use the firmware default runtime."""
    _armed(mgr, OperatingMode.STANDBY)

    await mgr.set_mode(OperatingMode.HEAT)

    sent = _sent(mgr)
    assert sent == [protocol_v3.encode_button(ButtonCode.HEAT)]


async def test_set_mode_to_standby_does_not_reapply_runtime(mgr):
    """Turning off must not re-apply a runtime."""
    _armed(mgr, OperatingMode.HEAT)
    mgr._state.run_end_time = datetime.now(UTC) + timedelta(seconds=3600)

    await mgr.set_mode(OperatingMode.STANDBY)

    sent = _sent(mgr)
    assert sent == [protocol_v3.encode_button(ButtonCode.OFF)]


async def test_set_mode_preservation_never_extends(mgr, monkeypatch):
    """Remaining time is floored to whole minutes, so a mode change can
    only ever shorten (by < 60s), never extend, the running timer."""
    _armed(mgr)
    _freeze(monkeypatch)
    mgr._state.run_end_time = _FIXED_NOW + timedelta(seconds=3599)
    monkeypatch.setattr("bedjet_hub.ble.manager.asyncio.sleep", AsyncMock())

    await mgr.set_mode(OperatingMode.COOL)

    assert _sent(mgr)[-1] == protocol_v3.encode_set_runtime(0, 59)


async def test_set_mode_preservation_has_one_minute_floor(mgr, monkeypatch):
    """With under a minute left, preserve one minute instead of the
    firmware's multi-hour mode default."""
    _armed(mgr)
    _freeze(monkeypatch)
    mgr._state.run_end_time = _FIXED_NOW + timedelta(seconds=30)
    monkeypatch.setattr("bedjet_hub.ble.manager.asyncio.sleep", AsyncMock())

    await mgr.set_mode(OperatingMode.COOL)

    assert _sent(mgr)[-1] == protocol_v3.encode_set_runtime(0, 1)


async def test_set_mode_preserves_from_raw_remaining_without_end_time(mgr, monkeypatch):
    """When no end-time estimate exists, fall back to the raw remaining
    seconds from the last notification."""
    _armed(mgr)
    mgr._state.run_end_time = None
    mgr._state.runtime_remaining_seconds = 600
    monkeypatch.setattr("bedjet_hub.ble.manager.asyncio.sleep", AsyncMock())

    await mgr.set_mode(OperatingMode.COOL)

    assert _sent(mgr)[-1] == protocol_v3.encode_set_runtime(0, 10)


async def test_v2_mode_change_does_not_reapply_runtime(mgr):
    """V2 has no standalone runtime write; its mode path is unchanged."""
    mgr._model = "v2"
    mgr._state.mode = OperatingMode.HEAT
    mgr._state.run_end_time = datetime.now(UTC) + timedelta(seconds=3600)
    mgr._set_mode_v2 = AsyncMock()
    mgr.set_runtime = AsyncMock()

    await mgr.set_mode(OperatingMode.COOL)

    mgr._set_mode_v2.assert_awaited_once_with(OperatingMode.COOL)
    mgr.set_runtime.assert_not_awaited()


async def test_temperature_change_does_not_touch_runtime(mgr):
    """Temperature adjustments must never re-apply or reset the timer."""
    _armed(mgr)
    mgr._state.run_end_time = datetime.now(UTC) + timedelta(seconds=3600)

    await mgr.set_temperature(25.0)

    sent = _sent(mgr)
    assert sent == [protocol_v3.encode_set_temperature(25.0)]


async def test_fan_change_does_not_touch_runtime(mgr):
    """Fan adjustments must never re-apply or reset the timer."""
    _armed(mgr)
    mgr._state.run_end_time = datetime.now(UTC) + timedelta(seconds=3600)

    await mgr.set_fan_speed(55)

    sent = _sent(mgr)
    assert sent == [protocol_v3.encode_set_fan(55)]


async def test_set_runtime_is_the_only_timer_control(mgr):
    """An explicit runtime write is passed straight through."""
    _armed(mgr)

    await mgr.set_runtime(2, 30)

    assert _sent(mgr) == [protocol_v3.encode_set_runtime(2, 30)]


# ---------------------------------------------------------------------------
# Metadata publication
#
# The hub caches whatever metadata the daemon pushes at IPC-connect time, so
# discovering the metadata is not enough on its own: it has to be published when
# it changes, otherwise a client that attached earlier keeps serving the empty
# snapshot it received.
# ---------------------------------------------------------------------------


async def test_connect_publishes_metadata_after_the_initial_reads(mgr, ble_device):
    """Metadata must be published once the handshake has gathered it."""
    events = []

    async def fake_reads():
        events.append("reads")

    mock_client = MagicMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()
    mgr.subscribe_metadata(lambda meta: events.append("metadata"))

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client),
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
        patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
        patch.object(mgr, "_perform_v3_initial_reads", new=fake_reads),
    ):
        await mgr.connect()

    assert events == ["reads", "metadata"]


async def test_metadata_subscriber_receives_the_metadata_object(mgr, ble_device):
    seen = []
    mock_client = MagicMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()
    mgr.subscribe_metadata(seen.append)

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client),
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
        patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
    ):
        await mgr.connect()

    assert seen
    assert seen[-1] is mgr.get_metadata()


async def test_unsubscribing_stops_metadata_notifications(mgr, ble_device):
    seen = []
    mock_client = MagicMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()
    unsubscribe = mgr.subscribe_metadata(seen.append)
    unsubscribe()

    with (
        patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client),
        patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
        patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
    ):
        await mgr.connect()

    assert seen == []


async def test_a_failing_metadata_subscriber_does_not_block_the_others(mgr, ble_device, caplog):
    seen = []

    def explode(_metadata):
        raise RuntimeError("subscriber exploded")

    mock_client = MagicMock()
    mock_client.services = []
    mock_client.start_notify = AsyncMock()
    mgr.subscribe_metadata(explode)
    mgr.subscribe_metadata(seen.append)

    with caplog.at_level(logging.ERROR, logger="bedjet_hub.ble.manager"):
        with (
            patch("bedjet_hub.ble.manager.establish_connection", new_callable=AsyncMock, return_value=mock_client),
            patch.object(mgr, "_resolve_ble_device", new_callable=AsyncMock, return_value=ble_device),
            patch.object(mgr, "_wait_for_ready", new_callable=AsyncMock),
        ):
            await mgr.connect()

    assert len(seen) == 1
    assert any("subscriber exploded" in str(r.exc_info) for r in caplog.records)


# ---------------------------------------------------------------------------
# Metadata read failures must be visible
#
# Both of these used to be silent: the exception was discarded and the caller
# skipped the assignment, so a hub with blank firmware/memory names produced no
# evidence anywhere of why.
# ---------------------------------------------------------------------------


async def test_biodata_read_failures_are_logged(mgr, caplog):
    mgr._client = MagicMock()
    mgr._client.write_gatt_char = AsyncMock()
    mgr._client.read_gatt_char = AsyncMock(side_effect=OSError("gatt read failed"))

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble.manager"):
        result = await mgr._read_biodata(BiodataRequestType.MEMORY_NAMES)

    assert result is None
    assert any("Biodata read failed" in r.message for r in caplog.records)


async def test_initial_reads_warn_when_nothing_could_be_read(mgr, caplog):
    mgr._client = MagicMock()
    mgr._client.write_gatt_char = AsyncMock()
    mgr._client.read_gatt_char = AsyncMock(side_effect=OSError("gatt read failed"))

    with caplog.at_level(logging.WARNING, logger="bedjet_hub.ble.manager"):
        await mgr._perform_v3_initial_reads()

    assert any("will stay blank" in r.message for r in caplog.records)
