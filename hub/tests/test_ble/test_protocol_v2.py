import pytest

from bedjet_hub.ble.const import V2_WAKE_PACKET, OperatingMode
from bedjet_hub.ble.protocol_v2 import (
    V2Mode,
    compute_v2_max_runtime_seconds,
    decode_status_notification,
    encode_mode_button,
    encode_settings,
    encode_temperature,
    wrap_command,
)


def test_wrap():
    assert wrap_command(bytes([0x01, 0x0B])) == V2_WAKE_PACKET


def test_mode():
    assert encode_mode_button(V2Mode.HEAT) == bytes([0x02, 0x01, 0x02])


def test_temp():
    assert encode_temperature(38.0, False) == bytes([0x02, 0x07, 76])


def test_settings():
    assert encode_settings(True, False) == bytes([0x02, 0x11, 0x00])


def test_heat():
    d = bytes(14)
    d = d[:4] + bytes([72]) + d[5:]
    s = decode_status_notification(d)
    assert s.mode == OperatingMode.HEAT
    assert s.fan_speed_percent == 40


def test_standby():
    d = bytes(14)
    d = d[:4] + bytes([0x14]) + d[5:]
    s = decode_status_notification(d)
    assert s.mode == OperatingMode.STANDBY


def test_wrong_len():
    with pytest.raises(ValueError):
        decode_status_notification(bytes(10))


def test_max_runtime():
    assert compute_v2_max_runtime_seconds(30, 50) == 12 * 3600
    assert compute_v2_max_runtime_seconds(38, 100) == 3600
