---
name: bedjet-mcp
description: Control BedJet sleep climate devices via MCP tools — temperature, modes, fan speed, biorhythm programs, presets, and device settings. Requires the bedjet-hub daemon running on the local network.
version: 1.0.0
author: bedjet-hub
license: GPL-3.0
metadata:
  hermes:
    tags: [Smart-Home, BedJet, BLE, Sleep, IoT]
    homepage: https://github.com/duoi/enhanced-bedjet
prerequisites:
  commands: [python3]
  services: [bedjet-hub.service]
---

# BedJet MCP Tools

Control a BedJet sleep climate device through Hermes Agent. The MCP server proxies tool calls to a local FastAPI hub that maintains the BLE connection.

## Architecture

```
Hermes Agent  →  mcp/server.py (stdio)  →  bedjet-hub (HTTP :8265)  →  BedJet (BLE)
```

The MCP server is a thin proxy. The hub does all real work: BLE connection management, command queuing, program scheduling, and state tracking.

## Prerequisites

- BedJet Hub daemon running (`bedjet-hub.service`) on the local network
- Python 3.11+ with `bedjet-hub` installed
- Bluetooth adapter on the hub host (BlueZ on Linux)

## When to Use

- "Set the bed to 22 degrees"
- "Turn on the BedJet" (sets mode to heat)
- "Start my bedtime program"
- "What's the BedJet status?"
- "Mute the beeps"
- "Turn off the BedJet" (sets mode to standby)

## Available Tools

All tools are prefixed `mcp_bedjet_` in Hermes.

### Device Control

| Tool | Description |
|------|-------------|
| `get_device_status` | Connection state, temperature, mode, runtime, metadata |
| `set_device_mode` | standby / heat / turbo / extended_heat / cool / dry |
| `set_target_temperature` | Target temp in Celsius (10.0–40.0) |
| `set_fan_speed` | Fan percentage (5–100) |
| `set_runtime` | Hours + minutes countdown timer |
| `set_led` | Enable/disable LED ring |
| `set_mute` | Mute/unmute device beeps |
| `sync_clock` | Sync device clock to hub system time |

### Presets

| Tool | Description |
|------|-------------|
| `activate_memory` | Activate device memory preset (slot 1, 2, or 3) |
| `activate_biorhythm` | Activate device biorhythm preset (slot 1, 2, or 3) |

### Programs (Biorhythm Sequences)

| Tool | Description |
|------|-------------|
| `list_programs` | List all saved programs |
| `create_program` | Create a multi-step temperature sequence |
| `get_program` | Get program details |
| `update_program` | Modify an existing program |
| `delete_program` | Delete a program |
| `activate_program` | Start a program at a given ISO 8601 time |
| `get_active_program` | Check what's currently running |
| `stop_program` | Stop the active program |

### Preferences

| Tool | Description |
|------|-------------|
| `get_preferences` | Temperature unit, default fan speed, auto clock sync |
| `update_preferences` | Change preferences |

## Common Workflows

### Critical: Order of Operations

The BedJet hardware behaves exactly like a physical remote control, with strict order-of-operations requirements. **If you send commands in the wrong order, they will be ignored or overwritten by the device's default memory.**

**Always follow this 3-step sequence for any manual control:**

1. **Check Current State:** ALWAYS call `get_device_status()` first. You must know what mode the device is currently in.
2. **Set Mode (Wake Up):** If the requested mode is the SAME as the current mode, DO NOT call `set_device_mode`. If the requested mode is DIFFERENT from the current mode (e.g., it is in `standby` and you want `heat`), call `set_device_mode(mode=...)`. 
   * **Wait 1-2 seconds** after setting the mode. When the BedJet changes mode, it instantly resets its temperature, fan speed, and runtime to the factory defaults for that mode.
3. **Set Parameters:** ONLY AFTER the mode has been set and the device has transitioned, send your parameter commands:
   * `set_target_temperature(celsius=...)` (Remember to convert Fahrenheit to Celsius!)
   * `set_fan_speed(percent=...)`
   * `set_runtime(hours=..., minutes=...)`

**Failure Example:** If you set the temperature to 25°C, and *then* set the mode to `heat`, the temperature will instantly revert to the factory default for `heat` (37°C), wiping out your 25°C command.
**Failure Example 2:** If you set the temperature to 25°C and runtime to 2 hours, but forget to set the mode, the device will silently accept the settings but remain off (`standby`).

### Quick Heat
```python
# 1. Check state
get_device_status() 

# 2. Set mode (if not already in heat)
set_device_mode(mode="heat")

# 3. Wait, then set parameters
set_target_temperature(celsius=28) # e.g. 82F
set_fan_speed(percent=40)
set_runtime(hours=2, minutes=30)
```

### Extended Heat (For >4 hours)
Standard `heat` mode is hard-limited by the hardware to 4 hours (14400 seconds) for safety. If the user requests heating for more than 4 hours, you MUST use `extended_heat` mode. Note: `extended_heat` has a maximum temperature limit of 33.5°C.

```python
set_device_mode(mode="extended_heat")
# wait 1s
set_target_temperature(celsius=30)
set_runtime(hours=8, minutes=0)
```

### Bedtime Program (Scheduled)
```
create_program(name="Bedtime", startTime="22:30", days=[0,1,2,3,4], steps=[
    {"mode": "heat", "temperatureC": 30, "fanSpeedPercent": 60, "durationMinutes": 10},
    {"mode": "heat", "temperatureC": 26, "fanSpeedPercent": 30, "durationMinutes": 30},
    {"mode": "cool", "temperatureC": 22, "fanSpeedPercent": 20, "durationMinutes": 60},
    {"mode": "standby", "durationMinutes": 0},
])
# Runs automatically every Mon-Fri at 22:30. No need to call activate_program().
```

### Manual Program Run
```
activate_program(programId="<id>", startTime="2026-04-12T22:30:00")
```

### Turn Off
```
set_device_mode(mode="standby")
```

## Quirks and Troubleshooting

### Zombie BLE Connection

**Symptom:** Device status shows "connected" but commands silently do nothing.

**Cause:** Previously, the pure `bleak` Python library could enter a zombie state where it thought it was connected but the OS-level BLE link had died. 

**Fix:** This was patched in **Hub v0.2.3** using the `bleak-retry-connector` library (the same DBus cache-manager used by Home Assistant). The hub daemon should now recover automatically. If you somehow still encounter this rare Linux DBus edge-case, the workaround is:
1. `bluetoothctl disconnect <MAC>` — manually kill the OS-level BLE link
2. `systemctl restart bedjet-hub.service` — let the hub reconnect natively

### Temperature Units

The device reports and accepts temperatures in Celsius. The `get_preferences` tool shows the user's display preference (`F` or `C`) but the device always operates in Celsius. Convert when presenting to the user if their preference is Fahrenheit.

### MAC Address

The device BLE MAC is configured via `BEDJET_ADDRESS` environment variable in the `.env` file (loaded by systemd's `EnvironmentFile`). Never hardcode MAC addresses in code or configs that go into version control.

### Hub Unreachable

If tools return "Hub unreachable", check:
1. `systemctl status bedjet-hub.service` — is it running?
2. Is port 8265 accessible? (`curl http://localhost:8265/api/device`)
3. Check logs: `journalctl -u bedjet-hub.service -f`

### mDNS Discovery

The hub advertises via mDNS as `_bedjet._tcp.local.` on the LAN. The PWA app uses this for auto-discovery. MCP tools connect to `localhost:8265` directly.

## Notes

- All temperature values are in Celsius internally
- Fan speed is 5–100% (BedJet minimum)
- Programs run on the hub, not the device — if the hub restarts, active programs resume from SQLite state
- The device supports 3 memory presets and 3 biorhythm presets stored on hardware
- Auto-reconnect runs with exponential backoff if BLE drops
