"""Device state and metadata dataclasses, plus jitter suppression."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .const import NotificationType, OperatingMode


@dataclass
class DeviceState:
    """Snapshot of the BedJet's current operating state.

    Populated from BLE status notifications. ``is_ready`` becomes
    True once a non-zero temperature reading has been received.
    """
    mode: OperatingMode = OperatingMode.STANDBY
    current_temperature_c: float = 0.0
    target_temperature_c: float = 0.0
    ambient_temperature_c: float = 0.0
    fan_speed_percent: int = 0
    runtime_remaining_seconds: int = 0
    run_end_time: datetime | None = None
    maximum_runtime_seconds: int = 0
    turbo_time_seconds: int = 0
    min_temperature_c: float = 0.0
    max_temperature_c: float = 0.0
    led_enabled: bool | None = None
    beeps_muted: bool | None = None
    dual_zone: bool | None = None
    units_setup: bool | None = None
    connection_test_passed: bool | None = None
    bio_sequence_step: int | None = None
    notification: NotificationType | None = None
    shutdown_reason: int | None = None
    update_phase: int | None = None

    @property
    def is_ready(self) -> bool:
        return self.current_temperature_c != 0.0

    @property
    def app_fan_speed_percent(self) -> int:
        return 0 if self.mode == OperatingMode.STANDBY else self.fan_speed_percent


@dataclass
class DeviceMetadata:
    """Static device info discovered during initial BLE handshake."""

    address: str = ""
    name: str = ""
    model: str = "v3"
    firmware_version: str | None = None
    memory_names: list[str | None] = field(default_factory=lambda: [None, None, None])
    biorhythm_names: list[str | None] = field(default_factory=lambda: [None, None, None])


class JitterSuppressor:
    """Filters small fluctuations in temperature and run-end-time values.

    The BedJet's BLE notifications can oscillate by ±0.5 °C between
    successive readings. This class suppresses those jitters so the UI
    only updates on meaningful changes.
    """

    def __init__(self):
        self._last_temp = None
        self._last_temp_time = None
        self._last_end_time = None

    def update_temperature(self, new_value, now):
        if self._last_temp is None:
            self._last_temp = new_value
            self._last_temp_time = now
            return True, new_value
        if new_value == self._last_temp:
            self._last_temp_time = now
            return False, self._last_temp
        if abs(new_value - self._last_temp) >= 1.0 or (now - self._last_temp_time).total_seconds() >= 15:
            self._last_temp = new_value
            self._last_temp_time = now
            return True, new_value
        return False, self._last_temp

    def update_end_time(self, new_end_time, now):
        if self._last_end_time is None:
            self._last_end_time = new_end_time
            return True, new_end_time
        if self._last_end_time < now and new_end_time and new_end_time > now:
            self._last_end_time = new_end_time
            return True, new_end_time
        if new_end_time is None or self._last_end_time is None:
            if new_end_time != self._last_end_time:
                self._last_end_time = new_end_time
                return True, new_end_time
            return False, self._last_end_time
        if abs((new_end_time - self._last_end_time).total_seconds()) >= 5:
            self._last_end_time = new_end_time
            return True, new_end_time
        return False, self._last_end_time
