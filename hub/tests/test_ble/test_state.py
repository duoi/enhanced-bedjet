from datetime import UTC, datetime, timedelta

from bedjet_hub.ble.const import OperatingMode
from bedjet_hub.ble.state import DeviceState, JitterSuppressor


def test_defaults():
    s = DeviceState()
    assert s.mode == OperatingMode.STANDBY
    assert s.current_temperature_c == 0.0
    assert not s.is_ready


def test_ready():
    assert DeviceState(current_temperature_c=22.0).is_ready


def test_standby_fan():
    assert DeviceState(mode=OperatingMode.STANDBY, fan_speed_percent=60).app_fan_speed_percent == 0


def test_jitter_first():
    j = JitterSuppressor()
    a, v = j.update_temperature(22.0, datetime.now(UTC))
    assert a and v == 22.0


def test_jitter_small():
    j = JitterSuppressor()
    t = datetime.now(UTC)
    j.update_temperature(22.0, t)
    a, v = j.update_temperature(22.3, t + timedelta(seconds=1))
    assert not a and v == 22.0


def test_jitter_large():
    j = JitterSuppressor()
    t = datetime.now(UTC)
    j.update_temperature(22.0, t)
    a, v = j.update_temperature(24.0, t + timedelta(seconds=1))
    assert a and v == 24.0
