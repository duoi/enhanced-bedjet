import pytest

from bedjet_hub.ble.const import ButtonCode, OperatingMode
from bedjet_hub.ble.protocol_v3 import (
    decode_biodata,
    decode_status_notification,
    decode_status_read,
    encode_button,
    encode_set_fan,
    fan_percent_to_step,
    fan_step_to_percent,
    temp_byte_to_c,
    temp_c_to_byte,
)


def test_temp():
    assert temp_c_to_byte(38.0) == 76
    assert temp_byte_to_c(76) == 38.0


def test_fan():
    assert fan_percent_to_step(60) == 11
    assert fan_step_to_percent(11) == 60


def test_decode_notif():
    d = bytes([0] * 4 + [1, 30, 0, 0x4A, 0x4C, 0x01, 0x0B, 2, 0x58, 0x26, 0x56, 0, 0, 0x48, 0, 0])
    s = decode_status_notification(d)
    assert s.mode == OperatingMode.HEAT
    assert s.fan_speed_percent == 60


def test_decode_notif_wrong():
    with pytest.raises(ValueError):
        decode_status_notification(bytes(10))


def test_decode_read():
    d = bytes([0, 0, 2, 0, 0, 0, 0, 0x34, 2, 1, 0])
    s = decode_status_read(d)
    assert s.dual_zone
    assert s.led_enabled
    assert not s.beeps_muted


def test_encode():
    assert encode_button(ButtonCode.HEAT) == bytes([0x01, 0x03])
    assert encode_set_fan(60) == bytes([0x07, 11])


def test_biodata_name():
    d = bytes([0x00, 0x00]) + b"BedJet\x00"
    r = decode_biodata(d)
    assert r["name"] == "BedJet"


def test_biodata_memory():
    s1 = b"Sleep\x00" + b"\x00" * 10
    s2 = b"\x00" + b"\x00" * 15
    s3 = b"\x01" + b"\x00" * 15
    r = decode_biodata(bytes([0x01, 0x00]) + s1 + s2 + s3)
    assert r["names"] == ["Sleep", "Default", None]
