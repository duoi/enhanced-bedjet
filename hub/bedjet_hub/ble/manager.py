"""BLE connection manager for BedJet V2 and V3 devices.

Handles discovery, connection lifecycle, command queuing, automatic
reconnection with exponential backoff, and notification parsing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from . import protocol_v2, protocol_v3
from .const import (
    BEDJET3_BIODATA_FULL_UUID,
    BEDJET3_COMMAND_UUID,
    BEDJET3_NAME_UUID,
    BEDJET3_SERVICE_UUID,
    BEDJET3_STATUS_UUID,
    BEDJET_V2_COMMAND_UUID,
    BEDJET_V2_SERVICE_UUID,
    BEDJET_V2_STATUS_UUID,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    STALE_DATA_TIMEOUT_SECONDS,
    V2_WAKE_PACKET,
    BiodataRequestType,
    ButtonCode,
    OperatingMode,
)
from .state import DeviceMetadata, DeviceState, JitterSuppressor

logger = logging.getLogger(__name__)


class BleManager:
    """Manages the BLE connection to a single BedJet device.

    Supports both V2 (ISSC-based) and V3 (Nordic-based) protocol
    variants. Command writes are serialized through an async queue
    to avoid interleaving on the single GATT characteristic.
    """

    def __init__(self, address=""):
        self._address = address
        self._client = None
        self._connected = False
        self._model = "v3"
        self._state = DeviceState()
        self._metadata = DeviceMetadata(address=address, model="v3")
        self._subscribers = []
        self._jitter = JitterSuppressor()
        self._command_queue = asyncio.Queue()
        self._reconnect_task = None
        self._command_worker_task = None
        self._last_activity = datetime.now(UTC)
        self._last_notification_time = None
        self._reconnect_attempts = 0
        self._shutdown = False
        self.on_connect: Callable[[], None] | None = None

    @property
    def is_connected(self):
        return self._connected

    def get_state(self):
        return self._state

    def get_metadata(self):
        return self._metadata

    def subscribe(self, cb):
        self._subscribers.append(cb)

        def unsub():
            if cb in self._subscribers:
                self._subscribers.remove(cb)

        return unsub

    def reset_activity_timer(self):
        self._last_activity = datetime.now(UTC)

    async def connect(self):
        """Establish a BLE connection. Cleans up partial state on failure."""
        if self._connected:
            return
        from bleak import BleakClient

        if not self._address:
            self._address = await self._scan_for_device()
            self._metadata.address = self._address
        client = BleakClient(self._address)
        try:
            await client.connect()
            v2s = any(
                ch.uuid.lower() == BEDJET_V2_STATUS_UUID.lower()
                for svc in client.services
                for ch in svc.characteristics
            )
            if v2s:
                self._model = "v2"
                self._metadata.model = "v2"
                self._metadata.name = "BedJet V2"
                self._metadata.firmware_version = "ISSC V2"
                await client.write_gatt_char(BEDJET_V2_COMMAND_UUID, V2_WAKE_PACKET)
            else:
                self._model = "v3"
            su = BEDJET_V2_STATUS_UUID if self._model == "v2" else BEDJET3_STATUS_UUID
            await client.start_notify(su, self._on_notification)
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._client = None
            raise
        self._client = client
        self._connected = True
        self._reconnect_attempts = 0
        self.reset_activity_timer()
        if self._model == "v3":
            await self._perform_v3_initial_reads()
        await self._wait_for_ready()
        self._command_worker_task = asyncio.create_task(self._command_worker())

    async def disconnect(self):
        self._shutdown = True
        if self._command_worker_task:
            self._command_worker_task.cancel()
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self._client and self._connected:
            try:
                su = BEDJET_V2_STATUS_UUID if self._model == "v2" else BEDJET3_STATUS_UUID
                await self._client.stop_notify(su)
            except Exception:
                pass
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._connected = False
        self._client = None

    async def set_mode(self, mode):
        if self._model == "v2":
            await self._set_mode_v2(mode)
        else:
            await self._enqueue_command(protocol_v3.encode_button(self._mode_to_button(mode)))
            await self._wait_for_mode_change(mode)

    async def set_fan_speed(self, pct):
        if self._model == "v2":
            await self._set_fan_v2(pct)
        else:
            await self._enqueue_command(protocol_v3.encode_set_fan(pct))

    async def set_temperature(self, c):
        if self._model == "v2":
            inner = protocol_v2.encode_temperature(c, self._state.beeps_muted or False)
            await self._enqueue_command(protocol_v2.wrap_command(inner))
        else:
            await self._enqueue_command(protocol_v3.encode_set_temperature(c))

    async def set_led(self, en):
        if self._model == "v2":
            inner = protocol_v2.encode_settings(en, self._state.beeps_muted or False)
            await self._enqueue_command(protocol_v2.wrap_command(inner))
        else:
            await self._enqueue_command(protocol_v3.encode_button(ButtonCode.LED_ON if en else ButtonCode.LED_OFF))
        self._state.led_enabled = en
        self._notify_subscribers(self._state)

    async def set_muted(self, m):
        if self._model == "v2":
            inner = protocol_v2.encode_settings(self._state.led_enabled or True, m)
            await self._enqueue_command(protocol_v2.wrap_command(inner))
        else:
            await self._enqueue_command(protocol_v3.encode_button(ButtonCode.MUTE if m else ButtonCode.UNMUTE))
        self._state.beeps_muted = m
        self._notify_subscribers(self._state)

    async def sync_clock(self):
        if self._model != "v3":
            return
        now = datetime.now()
        await self._enqueue_command(protocol_v3.encode_set_clock(now.hour, now.minute))

    async def set_runtime(self, h, m):
        if self._model != "v3":
            return
        await self._enqueue_command(protocol_v3.encode_set_runtime(h, m))

    async def activate_memory(self, slot):
        if self._model != "v3":
            return
        await self._enqueue_command(
            protocol_v3.encode_button({1: ButtonCode.M1, 2: ButtonCode.M2, 3: ButtonCode.M3}[slot])
        )

    async def activate_biorhythm(self, slot):
        if self._model != "v3":
            return
        await self._enqueue_command(
            protocol_v3.encode_button(
                {1: ButtonCode.BIORHYTHM_1, 2: ButtonCode.BIORHYTHM_2, 3: ButtonCode.BIORHYTHM_3}[slot]
            )
        )

    async def _enqueue_command(self, cmd):
        if not self._connected:
            raise RuntimeError("Not connected")
        await self._command_queue.put(cmd)

    async def _command_worker(self):
        while not self._shutdown:
            try:
                cmd = await asyncio.wait_for(self._command_queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            await self._write_command(cmd)

    async def _process_command_queue_once(self):
        try:
            cmd = self._command_queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            await self._write_command(cmd)
        except Exception:
            pass

    async def _write_command(self, cmd):
        if not self._client or not self._connected:
            raise RuntimeError("Not connected")
        cu = BEDJET_V2_COMMAND_UUID if self._model == "v2" else BEDJET3_COMMAND_UUID
        await self._client.write_gatt_char(cu, cmd)
        self.reset_activity_timer()

    def _on_notification(self, sender, data):
        self._last_notification_time = datetime.now(UTC)
        self.reset_activity_timer()
        try:
            raw = (
                protocol_v2.decode_status_notification(data)
                if self._model == "v2"
                else protocol_v3.decode_status_notification(data)
            )
        except ValueError:
            return
        now = datetime.now(UTC)
        acc, ct = self._jitter.update_temperature(raw.current_temperature_c, now)
        self._state.current_temperature_c = ct
        self._state.ambient_temperature_c = raw.ambient_temperature_c
        self._state.target_temperature_c = raw.target_temperature_c
        self._state.mode = raw.mode
        self._state.fan_speed_percent = raw.fan_speed_percent
        self._state.runtime_remaining_seconds = raw.runtime_remaining_seconds
        self._state.maximum_runtime_seconds = raw.maximum_runtime_seconds
        self._state.turbo_time_seconds = raw.turbo_time_seconds
        self._state.min_temperature_c = raw.min_temperature_c
        self._state.max_temperature_c = raw.max_temperature_c
        self._state.shutdown_reason = raw.shutdown_reason
        ne = now + timedelta(seconds=raw.runtime_remaining_seconds) if raw.runtime_remaining_seconds > 0 else None
        ea, et = self._jitter.update_end_time(ne, now)
        self._state.run_end_time = et
        if acc or ea:
            self._notify_subscribers(self._state)

    def _notify_subscribers(self, state):
        for cb in self._subscribers:
            try:
                cb(state)
            except Exception:
                pass

    async def _perform_v3_initial_reads(self):
        try:
            nd = await self._client.read_gatt_char(BEDJET3_NAME_UUID)
            self._metadata.name = nd.decode("utf-8", errors="replace").strip("\x00")
            sd = await self._client.read_gatt_char(BEDJET3_STATUS_UUID)
            fs = protocol_v3.decode_status_read(sd)
            self._state.led_enabled = fs.led_enabled
            self._state.beeps_muted = fs.beeps_muted
            self._state.dual_zone = fs.dual_zone
            self._state.units_setup = fs.units_setup
            self._state.connection_test_passed = fs.connection_test_passed
            for rt in [
                BiodataRequestType.FIRMWARE_VERSIONS,
                BiodataRequestType.MEMORY_NAMES,
                BiodataRequestType.BIORHYTHM_NAMES,
            ]:
                r = await self._read_biodata(rt)
                if r:
                    if rt == BiodataRequestType.FIRMWARE_VERSIONS and r.get("versions"):
                        self._metadata.firmware_version = r["versions"][0]
                    elif rt == BiodataRequestType.MEMORY_NAMES:
                        self._metadata.memory_names = r["names"]
                    elif rt == BiodataRequestType.BIORHYTHM_NAMES:
                        self._metadata.biorhythm_names = r["names"]
        except Exception as e:
            logger.warning(f"Initial reads failed: {e}")

    async def _read_biodata(self, rt):
        for tag in (0, 1):
            try:
                await self._client.write_gatt_char(BEDJET3_COMMAND_UUID, protocol_v3.encode_get_bio(rt, tag))
                await asyncio.sleep(0.1)
                data = await self._client.read_gatt_char(BEDJET3_BIODATA_FULL_UUID)
                r = protocol_v3.decode_biodata(data)
                if r.get("type") != "unknown":
                    return r
            except Exception:
                pass
        return None

    async def _wait_for_ready(self):
        dl = datetime.now(UTC) + timedelta(seconds=5)
        while not self._state.is_ready and datetime.now(UTC) < dl:
            await asyncio.sleep(0.1)

    async def _wait_for_mode_change(self, target):
        to = 5 if self._model == "v2" else 1
        dl = datetime.now(UTC) + timedelta(seconds=to)
        while self._state.mode != target and datetime.now(UTC) < dl:
            await asyncio.sleep(0.05)

    async def _set_mode_v2(self, mode):
        if mode == OperatingMode.STANDBY:
            cur = self._state.mode
            if cur == OperatingMode.STANDBY:
                return
            btn = {
                OperatingMode.TURBO: protocol_v2.V2Mode.TURBO,
                OperatingMode.HEAT: protocol_v2.V2Mode.HEAT,
                OperatingMode.COOL: protocol_v2.V2Mode.COOL,
            }.get(cur)
            if btn:
                await self._enqueue_command(protocol_v2.wrap_command(protocol_v2.encode_mode_button(btn)))
                await self._wait_for_mode_change(OperatingMode.STANDBY)
        else:
            if self._state.mode == mode and mode != OperatingMode.TURBO:
                return
            vm = {
                OperatingMode.TURBO: protocol_v2.V2Mode.TURBO,
                OperatingMode.HEAT: protocol_v2.V2Mode.HEAT,
                OperatingMode.COOL: protocol_v2.V2Mode.COOL,
            }.get(mode)
            if vm:
                await self._enqueue_command(protocol_v2.wrap_command(protocol_v2.encode_mode_button(vm)))
                await self._wait_for_mode_change(mode)

    async def _set_fan_v2(self, pct):
        cm = {
            OperatingMode.TURBO: protocol_v2.V2Mode.TURBO,
            OperatingMode.HEAT: protocol_v2.V2Mode.HEAT,
            OperatingMode.COOL: protocol_v2.V2Mode.COOL,
        }.get(self._state.mode, protocol_v2.V2Mode.HEAT)
        h = self._state.runtime_remaining_seconds // 3600
        m = (self._state.runtime_remaining_seconds % 3600) // 60
        inner = protocol_v2.encode_fan(
            pct, cm, self._state.target_temperature_c, self._state.beeps_muted or False, h, m
        )
        await self._enqueue_command(protocol_v2.wrap_command(inner))

    async def _scan_for_device(self):
        from bleak import BleakScanner

        devs = await BleakScanner.discover(timeout=10.0)
        for d in devs:
            if d.name and "bedjet" in d.name.lower():
                return d.address
            if d.metadata.get("uuids"):
                for u in d.metadata["uuids"]:
                    if u.lower() in (BEDJET3_SERVICE_UUID.lower(), BEDJET_V2_SERVICE_UUID.lower()):
                        return d.address
        raise RuntimeError("No BedJet found")

    def _compute_reconnect_delay(self, att):
        return min(RECONNECT_INITIAL_DELAY * (2**att), RECONNECT_MAX_DELAY)

    async def start_auto_reconnect(self):
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        while not self._shutdown:
            if self._connected:
                await asyncio.sleep(1)
                continue
            d = self._compute_reconnect_delay(self._reconnect_attempts)
            await asyncio.sleep(d)
            try:
                await self.connect()
                logger.info("BLE reconnection successful (attempt %d)", self._reconnect_attempts + 1)
                self._notify_subscribers(self._state)
                if self.on_connect:
                    self.on_connect()
            except Exception as exc:
                self._reconnect_attempts += 1
                logger.warning(
                    "BLE connection attempt %d failed: %s",
                    self._reconnect_attempts,
                    exc,
                )

    async def check_stale_data(self):
        if self._last_notification_time is None:
            return False
        return (datetime.now(UTC) - self._last_notification_time).total_seconds() > STALE_DATA_TIMEOUT_SECONDS

    @staticmethod
    def _mode_to_button(mode):
        return {
            OperatingMode.STANDBY: ButtonCode.OFF,
            OperatingMode.COOL: ButtonCode.COOL,
            OperatingMode.HEAT: ButtonCode.HEAT,
            OperatingMode.TURBO: ButtonCode.TURBO,
            OperatingMode.DRY: ButtonCode.DRY,
            OperatingMode.EXTENDED_HEAT: ButtonCode.EXTENDED_HEAT,
        }[mode]
