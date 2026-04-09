"""BedJet V3 (Nordic-based) BLE protocol: command encoding and status decoding.

The V3 protocol uses a 20-byte status notification, an 11-byte status
read, and variable-length biodata reads for names and firmware info.
"""

from __future__ import annotations

from .const import (
    NotificationType,
    OperatingMode,
)
from .state import DeviceState


def temp_c_to_byte(c):
    return round(c * 2)


def temp_byte_to_c(b):
    return b / 2.0


def fan_percent_to_step(p):
    return (p // 5) - 1


def fan_step_to_percent(s):
    return (s + 1) * 5


def decode_status_notification(data):
    if len(data) != 20:
        raise ValueError(f"Expected 20 bytes, got {len(data)}")
    s = DeviceState()
    s.runtime_remaining_seconds = data[4] * 3600 + data[5] * 60 + data[6]
    s.current_temperature_c = temp_byte_to_c(data[7])
    s.target_temperature_c = temp_byte_to_c(data[8])
    s.mode = OperatingMode(data[9])
    s.fan_speed_percent = fan_step_to_percent(data[10])
    s.maximum_runtime_seconds = data[11] * 3600 + data[12] * 60
    s.min_temperature_c = temp_byte_to_c(data[13])
    s.max_temperature_c = temp_byte_to_c(data[14])
    s.turbo_time_seconds = (data[15] << 8) | data[16]
    s.ambient_temperature_c = temp_byte_to_c(data[17])
    s.shutdown_reason = data[18]
    return s


def decode_status_read(data):
    if len(data) != 11:
        raise ValueError(f"Expected 11 bytes, got {len(data)}")
    s = DeviceState()
    s.dual_zone = bool(data[2] & 2)
    s.update_phase = data[6]
    s.connection_test_passed = bool(data[7] & 32)
    s.led_enabled = bool(data[7] & 16)
    s.units_setup = bool(data[7] & 4)
    s.beeps_muted = bool(data[7] & 1)
    s.bio_sequence_step = data[8] if data[8] != 0 else None
    s.notification = NotificationType(data[9]) if data[9] != 0 else None
    return s


def _parse_slots(payload, count):
    r = []
    for i in range(count):
        o = i * 16
        if o + 16 > len(payload):
            r.append(None)
            continue
        sl = payload[o : o + 16]
        if sl[0] == 0x01:
            r.append(None)
        elif sl[0] == 0x00:
            r.append("Default")
        else:
            r.append(sl.split(b"\x00", 1)[0].decode("utf-8", errors="replace"))
    return r


def decode_biodata(data):
    if len(data) < 2:
        raise ValueError("Too short")
    rt = data[0]
    p = data[2:]
    if rt == 0x00:
        return {"type": "device_name", "name": p.split(b"\x00", 1)[0].decode("utf-8", errors="replace")}
    elif rt == 0x01:
        return {"type": "memory_names", "names": _parse_slots(p, 3)}
    elif rt == 0x04:
        return {"type": "biorhythm_names", "names": _parse_slots(p, 3)}
    elif rt == 0x20:
        return {"type": "firmware_versions", "versions": [n for n in _parse_slots(p, 1) if n]}
    return {"type": "unknown", "raw": data.hex()}


def encode_button(btn):
    return bytes([0x01, btn])


def encode_set_fan(pct):
    return bytes([0x07, fan_percent_to_step(pct)])


def encode_set_temperature(c):
    return bytes([0x03, temp_c_to_byte(c)])


def encode_set_runtime(h, m):
    t = h * 60 + m
    return bytes([0x02, t // 60, t % 60])


def encode_set_clock(h, m):
    return bytes([0x08, h, m])


def encode_get_bio(rt, tag=0):
    return bytes([0x41, rt, tag])
