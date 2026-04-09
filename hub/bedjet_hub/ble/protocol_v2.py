"""BedJet V2 (ISSC-based) BLE protocol: command encoding and status decoding.

The V2 protocol uses a 14-byte status notification and wraps commands in
a packet with a 0x58 header and trailing checksum byte.
"""

from __future__ import annotations

from enum import IntEnum

from .const import (
    V2_MAX_RUNTIME_TABLE,
    OperatingMode,
)
from .state import DeviceState


class V2Mode(IntEnum):
    TURBO = 0x01
    HEAT = 0x02
    COOL = 0x03


def wrap_command(inner):
    pkt = bytes([0x58]) + inner
    return pkt + bytes([(0xFF - (sum(pkt) & 0xFF)) & 0xFF])


def encode_mode_button(m):
    return bytes([0x02, 0x01, int(m)])


def encode_temperature(c, muted):
    tb = round(max(19, min(43, c)) * 2)
    if muted:
        tb |= 0x80
    return bytes([0x02, 0x07, tb])


def encode_settings(led, muted):
    sb = 0
    if muted:
        sb |= 1
    if not led:
        sb |= 2
    return bytes([0x02, 0x11, sb])


def encode_fan(pct, mode, tgt, muted, h, m):
    step = pct // 5
    tb = round(tgt * 2)
    if muted:
        tb |= 0x80
    return bytes([0x07, 0x0E, int(mode), step, tb, h, m, 0x00])


def decode_status_notification(data):
    if len(data) != 14:
        raise ValueError(f"Expected 14 bytes, got {len(data)}")
    s = DeviceState()
    b4 = data[4]
    if 97 <= b4 <= 116:
        s.mode = OperatingMode.COOL
        s.fan_speed_percent = (b4 - 96) * 5
    elif 65 <= b4 <= 84:
        s.mode = OperatingMode.HEAT
        s.fan_speed_percent = (b4 - 64) * 5
    elif 33 <= b4 <= 52:
        s.mode = OperatingMode.TURBO
        s.fan_speed_percent = (b4 - 32) * 5
    elif b4 in (0x14, 0x0E) or data[5] == 0:
        s.mode = OperatingMode.STANDBY
        s.fan_speed_percent = 0
    elif data[5] in (1, 2, 3, 4):
        s.mode = OperatingMode.TURBO
        s.fan_speed_percent = 100
    else:
        s.mode = OperatingMode.STANDBY
        s.fan_speed_percent = 0
    if s.mode != OperatingMode.STANDBY:
        s.fan_speed_percent = max(5, min(100, s.fan_speed_percent))
    s.current_temperature_c = (data[3] & 0x7F) / 2.0
    s.led_enabled = (data[3] & 0x80) == 0
    s.target_temperature_c = (data[7] & 0x7F) / 2.0
    s.ambient_temperature_c = s.current_temperature_c
    if s.mode == OperatingMode.TURBO:
        s.target_temperature_c = 43.0
    s.beeps_muted = (data[8] & 0x80) != 0
    h = data[5] >> 4
    sub = ((data[5] & 0xF) << 8) | data[6]
    s.runtime_remaining_seconds = h * 3600 + ((sub * 60 + 32) // 64)
    s.turbo_time_seconds = max(0, 600 - data[11])
    s.min_temperature_c = 19.0
    s.max_temperature_c = 43.0
    s.maximum_runtime_seconds = compute_v2_max_runtime_seconds(s.target_temperature_c, s.fan_speed_percent)
    return s


def compute_v2_max_runtime_seconds(t, f):
    for thr, rules in V2_MAX_RUNTIME_TABLE:
        if t <= thr:
            for fl, rh in rules:
                if f <= fl:
                    return rh * 3600
    return 3600
