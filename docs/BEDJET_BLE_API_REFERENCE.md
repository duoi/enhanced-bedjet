# BedJet Device Protocol Specification

## 1. Scope
This document defines the BLE interface, command set, packet formats, normalized state model, and required client operations for implementing a BedJet controller.

Supported device families:

- `BedJet 3`
- `BedJet V2`

Implementation goals:

- Discover nearby devices
- Connect over BLE
- Subscribe to live state
- Control mode, fan, temperature, runtime, LED, and mute
- Read device metadata, preset names, and diagnostics

## 2. Conventions

- All byte values are unsigned 8-bit integers unless stated otherwise.
- Multi-byte integers are big-endian unless stated otherwise.
- Bit numbering uses `bit 0` as the least-significant bit.
- Temperatures are encoded as `Celsius * 2`.
- App-facing fan speed is a percentage in `5%` increments.
- The device should be treated as allowing a single active BLE connection at a time.

## 3. Model Capability Matrix

| Capability | BedJet 3 | BedJet V2 |
| --- | --- | --- |
| Mode: Standby | Yes | Yes |
| Mode: Heat | Yes | Yes |
| Mode: Turbo | Yes | Yes |
| Mode: Cool / Fan Only | Yes | Yes |
| Mode: Dry | Yes | No |
| Mode: Extended Heat | Yes | No |
| Explicit runtime write | Yes | No documented support |
| Device name read | Yes | No documented support |
| Firmware read | Yes | No documented support |
| Memory name read | Yes | No documented support |
| Biorhythm name read | Yes | No documented support |
| LED control | Yes | Yes |
| Mute control | Yes | Yes |
| Memory activation | Yes | Not documented |
| Biorhythm activation | Yes | Not documented |
| Wi-Fi credential characteristics present | Yes | No |

## 4. BLE Discovery

### 4.1 BedJet 3

- Service UUID: `00001000-bed0-0080-aa55-4265644a6574`
- Device is connectable

### 4.2 BedJet V2

- Service UUID: `49535343-fe7d-4ae5-8fa9-9fafd205e455`
- Local name prefix: `BEDJET`
- Device is connectable

## 5. GATT Definitions

### 5.1 BedJet 3

Service UUID:

- `00001000-bed0-0080-aa55-4265644a6574`

Characteristics:

| Name | UUID | Access | Purpose |
| --- | --- | --- | --- |
| Status | `00002000-bed0-0080-aa55-4265644a6574` | Read, Notify | Live state and device status |
| Name | `00002001-bed0-0080-aa55-4265644a6574` | Read | Device name |
| SSID | `00002002-bed0-0080-aa55-4265644a6574` | Unknown | Reserved for future investigation |
| Password | `00002003-bed0-0080-aa55-4265644a6574` | Unknown | Reserved for future investigation |
| Command | `00002004-bed0-0080-aa55-4265644a6574` | Write | Outbound commands |
| Biodata | `00002005-bed0-0080-aa55-4265644a6574` | Unknown | Reserved for future investigation |
| Biodata Full | `00002006-bed0-0080-aa55-4265644a6574` | Read | Biodata response payloads |

Other UUIDs:

- CCCD: `00002902-0000-1000-8000-00805f9b34fb`

Observed payload lengths:

- Status read: `11` bytes
- Status notification: `20` bytes

### 5.2 BedJet V2

Service UUID:

- `49535343-fe7d-4ae5-8fa9-9fafd205e455`

Characteristics:

| Name | UUID | Access | Purpose |
| --- | --- | --- | --- |
| Status | `49535343-1e4d-4bd9-ba61-23c647249616` | Notify | Live state |
| Command | `49535343-8841-43f4-a8d4-ecbe34729bb3` | Write | Outbound commands |

Observed payload lengths:

- Status notification: `14` bytes

## 6. Connection Procedure

### 6.1 Common Procedure

1. Scan for connectable devices matching the discovery rules.
2. Connect to the BLE peripheral.
3. Detect protocol family:
   - If `49535343-1e4d-4bd9-ba61-23c647249616` exists in the service table, treat the device as `BedJet V2`.
   - Otherwise treat it as `BedJet 3`.
4. For `BedJet V2`, send the wake packet (section `6.2`) before subscribing.
5. Subscribe to the status notification characteristic.
6. For `BedJet 3`, perform the initial reads (section `6.3`) after subscribing. Subscribing first is required so that state notifications arriving during the read sequence are not lost.
7. Reject notification frames with unexpected lengths (`20` for `BedJet 3`, `14` for `BedJet V2`).
8. Serialize all writes and synchronous metadata reads through a per-device command queue.
9. Wait for the first notification with a non-zero current temperature before considering the device ready. Use a `5` second timeout. If the timeout expires, proceed with whatever state is available.
10. Disconnect after `60` seconds of inactivity unless a live control screen requires a persistent session.

### 6.2 BedJet V2 Connect Handshake

Immediately after connect and before subscribing, send this fixed wake packet to the command characteristic using write-without-response:

```text
58 01 0B 9B
```

Then subscribe to the status characteristic. On `BedJet V2`, set the device name to `"BedJet V2"` and firmware version to `"ISSC V2"` since these are not readable from the device.

### 6.3 BedJet 3 Initial Reads

After subscribing to notifications, perform these reads in order:

1. Status read (section `10.4`)
2. Name read from `00002001-bed0-0080-aa55-4265644a6574`
3. Firmware read via `GET_BIO` (section `8.4`)
4. Memory names read via `GET_BIO` (section `8.4`)
5. Biorhythm names read via `GET_BIO` (section `8.4`)

Each `GET_BIO` read uses the retry logic described in section `8.4`.

### 6.4 Disconnect Procedure

1. Cancel any pending idle timeout timer.
2. Stop notifications on the status characteristic.
3. Close the BLE connection.

If stopping notifications fails, log the error and proceed to close the connection anyway.

### 6.5 Unexpected Disconnect

On unexpected disconnect:

- Log a warning.
- Clear the client reference.
- On the next operation that requires a connection, attempt a fresh connect using the full procedure from section `6.1`.

The device protocol layer itself does not implement automatic reconnection. The caller (app layer or coordinator) is responsible for retrying operations when a connection-related error occurs.

### 6.6 Stale Data Detection

Track the timestamp of the last received notification. Consider data stale if no notification has been received in the last `60` seconds. The caller can use this signal to trigger a reconnect or display a stale-data indicator in the UI.

### 6.7 Idle Timeout

After each successful BLE operation (read, write, or notification received), reset a `60` second idle timer. When the timer fires, execute the disconnect procedure from section `6.4`. If a new operation arrives while disconnected, reconnect transparently.

## 7. Common Domain Enums

### 7.1 Operating Mode

| Name | Value | Meaning |
| --- | --- | --- |
| `STANDBY` | `0` | Off |
| `HEAT` | `1` | Heated mode |
| `TURBO` | `2` | High heat, limited time |
| `EXTENDED_HEAT` | `3` | Longer heat run |
| `COOL` | `4` | Fan only |
| `DRY` | `5` | High speed, no heat |
| `WAIT` | `6` | Biorhythm waiting step |

### 7.2 Notification Type

| Name | Value |
| --- | --- |
| `NONE` | `0` |
| `CLEAN_FILTER` | `1` |
| `UPDATE_AVAILABLE` | `2` |
| `UPDATE_FAILED` | `3` |
| `BIO_FAIL_CLOCK_NOT_SET` | `4` |
| `BIO_FAIL_TOO_LONG` | `5` |

### 7.3 Biodata Request Type

| Name | Value | Meaning |
| --- | --- | --- |
| `DEVICE_NAME` | `0x00` | Read device name |
| `MEMORY_NAMES` | `0x01` | Read `M1` to `M3` names |
| `BIORHYTHM_NAMES` | `0x04` | Read biorhythm names |
| `FIRMWARE_VERSIONS` | `0x20` | Read firmware version strings |

## 8. BedJet 3 Commands

### 8.1 Command Write Rules

- All commands are written directly to `00002004-bed0-0080-aa55-4265644a6574`.
- Command format is raw bytes with no outer wrapper.
- Default write mode is write-with-response.
- `GET_BIO` specifically requires write-with-response because the response payload must be read immediately after the write completes.

### 8.2 Command Opcodes

| Opcode | Name | Payload | Notes |
| --- | --- | --- | --- |
| `0x01` | `BUTTON` | `[button]` | Button action |
| `0x02` | `SET_RUNTIME` | `[hours, minutes]` | Runtime write |
| `0x03` | `SET_TEMPERATURE` | `[temp2x]` | Temperature write |
| `0x04` | `SET_STEP` | Unknown | Reserved |
| `0x05` | `SET_HACKS` | Unknown | Reserved |
| `0x06` | `STATUS` | Unknown | Reserved |
| `0x07` | `SET_FAN` | `[fanStep]` | Fan write |
| `0x08` | `SET_CLOCK` | `[hour, minute]` | Clock write |
| `0x40` | `SET_BIO` | Unknown | Reserved |
| `0x41` | `GET_BIO` | `[requestType, tag]` | Biodata request |

### 8.3 Button Codes

| Button | Value | Use |
| --- | --- | --- |
| `OFF` | `0x01` | Turn off |
| `COOL` | `0x02` | Fan-only mode |
| `HEAT` | `0x03` | Heat mode |
| `TURBO` | `0x04` | Turbo mode |
| `DRY` | `0x05` | Dry mode |
| `EXTENDED_HEAT` | `0x06` | Extended heat |
| `M1` | `0x20` | Memory slot 1 |
| `M2` | `0x21` | Memory slot 2 |
| `M3` | `0x22` | Memory slot 3 |
| `DEBUG_ON` | `0x40` | Reserved |
| `DEBUG_OFF` | `0x41` | Reserved |
| `CONNECTION_TEST` | `0x42` | Reserved |
| `UPDATE_FIRMWARE` | `0x43` | Reserved |
| `LED_ON` | `0x46` | Enable LED ring |
| `LED_OFF` | `0x47` | Disable LED ring |
| `MUTE` | `0x48` | Mute beeps |
| `UNMUTE` | `0x49` | Unmute beeps |
| `NOTIFY_ACK` | `0x52` | Reserved |
| `BIORHYTHM_1` | `0x80` | Start biorhythm 1 |
| `BIORHYTHM_2` | `0x81` | Start biorhythm 2 |
| `BIORHYTHM_3` | `0x82` | Start biorhythm 3 |

### 8.4 Implemented Command Formats

#### `BUTTON`

```text
[0x01, button]
```

Examples:

- Off: `[0x01, 0x01]`
- Heat: `[0x01, 0x03]`
- LED off: `[0x01, 0x47]`
- Biorhythm 2: `[0x01, 0x81]`

#### `SET_RUNTIME`

```text
[0x02, hours, minutes]
```

Rules:

- Normalize minutes so `minutes < 60`.
- Use only on `BedJet 3`.

#### `SET_TEMPERATURE`

```text
[0x03, round(celsius * 2)]
```

Rules:

- Temperature resolution is `0.5 C`.
- Clamp to the current min and max temperatures reported by the device.

#### `SET_FAN`

```text
[0x07, fanStep]
```

Rules:

- `fanPercent` valid range: `5` through `100`
- `fanStep = (fanPercent / 5) - 1`
- `fanStep` valid range: `0` through `19`

#### `SET_CLOCK`

```text
[0x08, hour, minute]
```

Rules:

- `hour` must be `0-23`
- `minute` must be `0-59`

#### `GET_BIO`

```text
[0x41, requestType, tag]
```

Observed requests:

- Device name: `[0x41, 0x00, tag]`
- Memory names: `[0x41, 0x01, tag]`
- Biorhythm names: `[0x41, 0x04, tag]`
- Firmware versions: `[0x41, 0x20, tag]`

Response flow:

1. Write `GET_BIO` to the command characteristic using write-with-response.
2. Read `00002006-bed0-0080-aa55-4265644a6574`.
3. Parse the returned payload using the biodata rules in section `10.5`.

Retry logic:

- Start with `tag = 0`.
- If the parsed response does not yield a valid result (e.g. the target field remains `null`), retry with `tag = 1`.
- Stop after `tag = 1`. If no valid result is obtained after both attempts, treat the field as unavailable and log a warning.

## 9. BedJet V2 Commands

### 9.1 Command Write Rules

- All commands are written to `49535343-8841-43f4-a8d4-ecbe34729bb3`.
- Every command is wrapped using the format in section `9.2`.
- All writes use write-without-response (`response=false`).

### 9.2 Wrapper Format

Wrapped packet:

```text
[0x58] + innerCommand + [checksum]
```

Checksum:

```text
checksum = (0xFF - (sum([0x58] + innerCommand) & 0xFF)) & 0xFF
```

### 9.3 Wake Packet

Full packet sent immediately after connect:

```text
58 01 0B 9B
```

### 9.4 Mode Button Command

Inner command:

```text
[0x02, 0x01, button]
```

Observed button values:

| Button | Value | Meaning |
| --- | --- | --- |
| `0x01` | Turbo | Toggle Turbo |
| `0x02` | Heat | Toggle Heat |
| `0x03` | Cool | Toggle Cool |

Mode behavior:

- To enter Turbo, send button `0x01`.
- To enter Heat, send button `0x02`.
- To enter Cool, send button `0x03`.
- To turn off, send the button for the currently active mode again.
- `Dry` and `Extended Heat` are not documented for `BedJet V2`.

### 9.5 Temperature Command

Inner command:

```text
[0x02, 0x07, tempByte]
```

Rules:

- `tempByte = round(celsius * 2)`
- If mute state must be preserved, set `tempByte |= 0x80`
- Clamp to `19.0 C` through `43.0 C`

### 9.6 Settings Command

Inner command:

```text
[0x02, 0x11, settingsByte]
```

Bit meanings:

| Bit | Meaning |
| --- | --- |
| `0` | Mute enabled |
| `1` | LED off |

Rules:

- Preserve the non-target setting on every write.
- To enable LED, clear `bit 1`.
- To disable LED, set `bit 1`.
- To enable mute, set `bit 0`.
- To disable mute, clear `bit 0`.

### 9.7 Fan Command

Inner command:

```text
[0x07, 0x0E, modeId, step, tempByte, hours, minutes, 0x00]
```

`modeId` values:

| Value | Meaning |
| --- | --- |
| `0x01` | Turbo |
| `0x02` | Heat |
| `0x03` | Cool |

Rules:

- `step = fanPercent / 5`
- `fanPercent` valid range: `5` through `100`
- `step` valid range: `1` through `20`
- `tempByte = round(targetCelsius * 2)`
- If mute state must be preserved, set `tempByte |= 0x80`
- `hours` and `minutes` must be copied from the currently tracked runtime remaining
- The final byte is always `0x00`

## 10. Response and State Decoding

### 10.1 State Initialization

Before the first notification is received, initialize the state with:

- `currentTemperatureC = 0`
- `targetTemperatureC = 0`
- `ambientTemperatureC = 0`
- `mode = STANDBY`
- `fanSpeedPercent = 0`
- `runtimeRemainingSeconds = 0`
- `runEndTime = null`
- `maximumRuntimeSeconds = 0`
- `turboTimeSeconds = 0`
- `minTemperatureC = 0`
- `maxTemperatureC = 0`
- All diagnostic fields: `null`

The device is considered ready when a notification yields `currentTemperatureC != 0`. Wait up to `5` seconds for this condition after connect. If the timeout expires, proceed with the zero-initialized state.

### 10.2 Normalized State Contract

Expose a normalized state object with these fields:

| Field | Type | Description |
| --- | --- | --- |
| `model` | `v2 | v3` | Device family |
| `name` | `string` | Device name |
| `firmwareVersion` | `string \| null` | Firmware version if available |
| `mode` | enum | Current operating mode |
| `currentTemperatureC` | `number` | Current outlet temperature |
| `targetTemperatureC` | `number` | Setpoint |
| `ambientTemperatureC` | `number` | Ambient temperature if available |
| `fanSpeedPercent` | `number` | Current fan speed |
| `runtimeRemainingSeconds` | `number` | Remaining runtime |
| `runEndTime` | `datetime \| null` | Derived end time |
| `maximumRuntimeSeconds` | `number` | Device or estimated max runtime |
| `turboTimeSeconds` | `number` | Remaining turbo time |
| `minTemperatureC` | `number` | Minimum supported setpoint |
| `maxTemperatureC` | `number` | Maximum supported setpoint |
| `ledEnabled` | `boolean \| null` | LED ring state |
| `beepsMuted` | `boolean \| null` | Mute state |
| `dualZone` | `boolean \| null` | Dual-zone configuration |
| `unitsSetup` | `boolean \| null` | Device has unit config |
| `connectionTestPassed` | `boolean \| null` | Diagnostic status |
| `bioSequenceStep` | `number \| null` | Active biorhythm step |
| `notification` | enum \| null | Notification type |
| `shutdownReason` | `number \| null` | Raw reason code |
| `updatePhase` | `number \| null` | Raw update phase |
| `memoryNames` | `[string\|null, string\|null, string\|null]` | `M1` to `M3` names |
| `biorhythmNames` | `[string\|null, string\|null, string\|null]` | Biorhythm names |

Normalization rules:

- If the device is in `STANDBY`, the app layer should expose `fanSpeedPercent = 0`.
- Preserve the last non-zero fan speed separately if the UI needs it.
- On `BedJet V2`, use the current temperature as ambient temperature.
- On `BedJet V2`, when in `TURBO`, report `targetTemperatureC = 43.0`.

### 10.3 BedJet 3 Status Notification

Frame length:

- `20` bytes

Field mapping:

| Byte | Meaning |
| --- | --- |
| `0-3` | Reserved |
| `4` | Runtime hours remaining |
| `5` | Runtime minutes remaining |
| `6` | Runtime seconds remaining |
| `7` | Current temperature, `C * 2` |
| `8` | Target temperature, `C * 2` |
| `9` | `OperatingMode` |
| `10` | Fan step |
| `11` | Maximum runtime hours |
| `12` | Maximum runtime minutes |
| `13` | Minimum temperature, `C * 2` |
| `14` | Maximum temperature, `C * 2` |
| `15-16` | Turbo time seconds, big-endian |
| `17` | Ambient temperature, `C * 2` |
| `18` | Shutdown reason |
| `19` | Reserved |

Derived values:

- `currentTemperatureC = byte7 / 2`
- `targetTemperatureC = byte8 / 2`
- `minTemperatureC = byte13 / 2`
- `maxTemperatureC = byte14 / 2`
- `fanSpeedPercent = (byte10 + 1) * 5`
- `runtimeRemainingSeconds = byte4 * 3600 + byte5 * 60 + byte6`
- `maximumRuntimeSeconds = byte11 * 3600 + byte12 * 60`
- `turboTimeSeconds = uint16(byte15, byte16)`

### 10.4 BedJet 3 Status Read

Frame length:

- `11` bytes

Field mapping:

| Byte | Meaning |
| --- | --- |
| `0-1` | Reserved |
| `2` | Status flags A |
| `3-5` | Reserved |
| `6` | Update phase |
| `7` | Status flags B |
| `8` | Bio sequence step |
| `9` | Notification type |
| `10` | Reserved |

Decoded bits:

### Byte 2

| Bit | Meaning |
| --- | --- |
| `1` | Dual-zone enabled |

### Byte 7

| Bit | Meaning |
| --- | --- |
| `5` | Connection test passed |
| `4` | LED enabled |
| `2` | Units configured |
| `0` | Beeps muted |

### 10.5 BedJet 3 Biodata Response

Response source:

- Read `00002006-bed0-0080-aa55-4265644a6574` after sending `GET_BIO`

Response format:

```text
[responseType, tag, payload...]
```

`responseType` values:

| Value | Meaning |
| --- | --- |
| `0x00` | Device name |
| `0x01` | Memory names |
| `0x04` | Biorhythm names |
| `0x20` | Firmware versions |

Text parsing rules:

- Text payload starts at byte `2`.
- Device name is a NUL-terminated string.
- Memory names are parsed as `16`-byte slots.
- Biorhythm names are parsed as `16`-byte slots.
- Firmware versions are parsed as `16`-byte slots.
- Slot parsing stops at the first NUL byte in each slot.
- If the first byte of a slot is `0x00`, interpret the slot as `"Default"`.
- If the first byte of a slot is `0x01`, interpret the slot as `null`.

Normalization rules:

- Use the first three memory slots as `M1`, `M2`, and `M3`.
- Use the first three biorhythm slots as biorhythm `1`, `2`, and `3`.
- Use the first firmware slot as the displayed firmware version.

### 10.6 BedJet V2 Status Notification

Frame length:

- `14` bytes

### Mode and Fan Decoding

Primary mode source:

- `byte4`

| Condition | Mode | Fan speed formula |
| --- | --- | --- |
| `97 <= byte4 <= 116` | `COOL` | `(byte4 - 96) * 5` |
| `65 <= byte4 <= 84` | `HEAT` | `(byte4 - 64) * 5` |
| `33 <= byte4 <= 52` | `TURBO` | `(byte4 - 32) * 5` |
| `byte4 == 0x14` | `STANDBY` | no active fan |
| `byte4 == 0x0E` | `STANDBY` | no active fan |
| `byte5 == 0x00` | `STANDBY` | no active fan |

Fallback:

- If `byte5` is in `0x01` through `0x04` and the packet otherwise looks like standby, treat the mode as `TURBO` and fan speed as `100`.

Fan normalization:

- If mode is not `STANDBY`, round to the nearest `5`.
- Clamp active fan speed to `5` through `100`.
- If mode is `STANDBY`, expose `fanSpeedPercent = 0` at the app layer.

### Temperature and Flag Decoding

| Byte | Meaning |
| --- | --- |
| `3` | Current temperature and LED flag |
| `7` | Target temperature |
| `8` | Status flags |
| `11` | Turbo timer progress |

Decoded values:

- `currentTemperatureC = (byte3 & 0x7F) / 2`
- `targetTemperatureC = (byte7 & 0x7F) / 2`
- `ledEnabled = ((byte3 & 0x80) == 0)`
- `beepsMuted = ((byte8 & 0x80) != 0)`
- `ambientTemperatureC = currentTemperatureC`
- If mode is `TURBO`, set `targetTemperatureC = 43.0`

### Runtime Decoding

Runtime source:

- `byte5`
- `byte6`

Formula:

```text
hours = byte5 >> 4
subRaw = ((byte5 & 0x0F) << 8) | byte6
runtimeRemainingSeconds = hours * 3600 + ((subRaw * 60 + 32) // 64)
```

Turbo time:

```text
turboTimeSeconds = max(0, 600 - byte11)
```

Temperature limits:

- `minTemperatureC = 19.0`
- `maxTemperatureC = 43.0`

### 10.7 BedJet V2 Maximum Runtime Estimation

`BedJet V2` does not report maximum runtime directly. Estimate it from target temperature and fan speed using the table below.

Select the first temperature threshold where:

```text
targetTemperatureC <= threshold
```

Then select the first rule in that row where:

```text
fanSpeedPercent <= fanLimit
```

Return the corresponding runtime hours.

| Temperature threshold | Fan rules |
| --- | --- |
| `33.5` | `<=100 -> 12h` |
| `34.0` | `<=70 -> 12h`, `<=100 -> 4h` |
| `34.5` | `<=60 -> 12h`, `<=100 -> 4h` |
| `35.5` | `<=50 -> 12h`, `<=100 -> 4h` |
| `36.5` | `<=20 -> 12h`, `<=40 -> 6h`, `<=100 -> 4h` |
| `37.5` | `<=30 -> 6h`, `<=50 -> 4h`, `<=100 -> 2h` |
| `38.5` | `<=20 -> 6h`, `<=30 -> 4h`, `<=50 -> 2h`, `<=100 -> 1h` |
| `39.5` | `<=20 -> 6h`, `<=30 -> 4h`, `<=40 -> 2h`, `<=100 -> 1h` |
| `inf` | `<=20 -> 4h`, `<=40 -> 2h`, `<=100 -> 1h` |

### 10.8 Jitter Suppression

The device sends frequent notifications with small fluctuations in temperature and runtime values. Without suppression, these cause excessive state updates and UI flicker.

#### Temperature Limiter

Apply to `currentTemperatureC` and `ambientTemperatureC` separately.

Rules:

- Accept the new value if this is the first reading.
- Accept if the absolute change is `>= 1.0 C`.
- Accept if `>= 15 seconds` have passed since the last accepted value.
- If the new value equals the current value exactly, reset the timer but do not emit a new state update.
- Otherwise, suppress the new value and report the previously accepted value.

#### End Time Limiter

Apply to the derived `runEndTime`.

Rules:

- Compute `newEndTime = now + runtimeRemaining`.
- If no previous end time exists, accept.
- If the previous end time is in the past and the new runtime is positive, accept (new run started).
- If the absolute difference between the old and new end times is `>= 5 seconds`, accept.
- Otherwise, suppress and report the previously accepted end time.
- If `runtimeRemaining == 0` and the previous end time is already expired, do not update.

## 11. Required Client Operations

Implement these public operations.

| Operation | Inputs | Models | Behavior |
| --- | --- | --- | --- |
| `scan()` | none | Both | Return discoverable devices matching section `4` |
| `connect(address)` | address | Both | Connect, detect model, subscribe, perform startup reads |
| `disconnect()` | none | Both | Stop notifications and close BLE connection |
| `subscribeState(callback)` | callback | Both | Deliver normalized state updates |
| `readState()` | none | Both | Return current normalized state |
| `readMetadata()` | none | Both | Return name, model, firmware, memory names, biorhythm names, capabilities |
| `setMode(mode)` | mode enum | Both | Change mode if supported |
| `setFanSpeedPercent(percent)` | `5-100` | Both | Change fan speed |
| `setTargetTemperatureC(celsius)` | number | Both | Change setpoint within supported range |
| `setLedEnabled(enabled)` | boolean | Both | Toggle LED ring |
| `setBeepsMuted(muted)` | boolean | Both | Toggle beeps |
| `syncClock(hour, minute)` | `0-23`, `0-59` | BedJet 3 | Set device clock |
| `setRuntimeRemaining(hours, minutes)` | integers | BedJet 3 | Set runtime |
| `activateMemory(slot)` | `1-3` | BedJet 3 | Trigger memory preset |
| `activateBiorhythm(slot)` | `1-3` | BedJet 3 | Trigger biorhythm preset |

Model-specific behavior:

- `setMode(DRY)` must reject on `BedJet V2`.
- `setMode(EXTENDED_HEAT)` must reject on `BedJet V2`.
- `setRuntimeRemaining()` must reject on `BedJet V2`.
- `activateMemory()` and `activateBiorhythm()` should be treated as unsupported on `BedJet V2` unless validated on real hardware.

### 11.1 `setMode()` Confirmation

After sending a mode change command, wait for a notification confirming the mode has changed before returning.

`BedJet 3`:

- Wait up to `1 second` for a notification where `mode == requestedMode`.
- If the timeout expires, log a warning and return anyway.

`BedJet V2`:

- Wait up to `5 seconds` for a notification where `mode == requestedMode`.
- If the timeout expires, log a warning and return anyway.

`BedJet V2` additional `setMode(STANDBY)` rules:

- Look up the current mode from state.
- If the current mode is `TURBO`, send button `0x01`. If `HEAT`, send `0x02`. If `COOL`, send `0x03`.
- If the current mode is already `STANDBY`, do nothing and return immediately.
- After sending, wait up to `5 seconds` for a notification confirming `STANDBY`.

`BedJet V2` additional `setMode(non-STANDBY)` rules:

- If the device is already in the requested mode (and it is not `TURBO`), do nothing and return.
- `TURBO` always sends the command even if already in `TURBO` mode.

### 11.2 `setLedEnabled()` and `setBeepsMuted()` Optimistic Update

After sending the LED or mute command, immediately update the local state for `ledEnabled` or `beepsMuted` and fire callbacks without waiting for a notification confirmation. This provides instant UI feedback.

### 11.3 `setFanSpeedPercent()` on BedJet V2

The `BedJet V2` fan command embeds the full current device context into the packet. The implementation must:

1. Read the current operating mode from state and map it to a `modeId` (`0x01` Turbo, `0x02` Heat, `0x03` Cool). Default to `0x02` if the mode does not map.
2. Compute `step = fanPercent / 5`.
3. Read the current `runtimeRemainingSeconds` from state and decompose into `hours` and `minutes`.
4. Compute `tempByte = round(targetTemperatureC * 2)`.
5. If `beepsMuted` is true, set `tempByte |= 0x80`.
6. Assemble the inner command: `[0x07, 0x0E, modeId, step, tempByte, hours, minutes, 0x00]`.
7. Wrap and send.

Failure to include the correct current state in this command will cause the device to reset temperature, runtime, or mute to incorrect values.

### 11.4 `setTargetTemperatureC()` on BedJet V2

The `BedJet V2` temperature command also carries the mute flag. The implementation must:

1. Compute `tempByte = round(celsius * 2)`.
2. If `beepsMuted` is true, set `tempByte |= 0x80`.
3. Assemble the inner command: `[0x02, 0x07, tempByte]`.
4. Wrap and send.

### 11.5 `setLedEnabled()` and `setBeepsMuted()` on BedJet V2

Both operations use the same settings command. The implementation must preserve the other setting:

1. Start with `settingsByte = 0x00`.
2. To set mute: if `muted`, set `bit 0`. To preserve LED: if `ledEnabled` is currently `false`, set `bit 1`.
3. To set LED: if `not enabled`, set `bit 1`. To preserve mute: if `beepsMuted` is currently `true`, set `bit 0`.
4. Assemble the inner command: `[0x02, 0x11, settingsByte]`.
5. Wrap and send.

## 12. Command-to-Operation Mapping

### 12.1 BedJet 3

| Operation | Command |
| --- | --- |
| `setMode(STANDBY)` | `[0x01, 0x01]` |
| `setMode(COOL)` | `[0x01, 0x02]` |
| `setMode(HEAT)` | `[0x01, 0x03]` |
| `setMode(TURBO)` | `[0x01, 0x04]` |
| `setMode(DRY)` | `[0x01, 0x05]` |
| `setMode(EXTENDED_HEAT)` | `[0x01, 0x06]` |
| `setLedEnabled(true)` | `[0x01, 0x46]` |
| `setLedEnabled(false)` | `[0x01, 0x47]` |
| `setBeepsMuted(true)` | `[0x01, 0x48]` |
| `setBeepsMuted(false)` | `[0x01, 0x49]` |
| `activateMemory(1)` | `[0x01, 0x20]` |
| `activateMemory(2)` | `[0x01, 0x21]` |
| `activateMemory(3)` | `[0x01, 0x22]` |
| `activateBiorhythm(1)` | `[0x01, 0x80]` |
| `activateBiorhythm(2)` | `[0x01, 0x81]` |
| `activateBiorhythm(3)` | `[0x01, 0x82]` |
| `setFanSpeedPercent(p)` | `[0x07, (p / 5) - 1]` |
| `setTargetTemperatureC(t)` | `[0x03, round(t * 2)]` |
| `setRuntimeRemaining(h, m)` | `[0x02, h, m]` |
| `syncClock(h, m)` | `[0x08, h, m]` |

### 12.2 BedJet V2

All commands below must be wrapped using section `9.2`.

| Operation | Inner command |
| --- | --- |
| `setMode(TURBO)` | `[0x02, 0x01, 0x01]` |
| `setMode(HEAT)` | `[0x02, 0x01, 0x02]` |
| `setMode(COOL)` | `[0x02, 0x01, 0x03]` |
| `setMode(STANDBY)` | resend current mode button |
| `setTargetTemperatureC(t)` | `[0x02, 0x07, round(t * 2)]` with mute-preserve bit if needed |
| `setLedEnabled(enabled)` | `[0x02, 0x11, settingsByte]` |
| `setBeepsMuted(muted)` | `[0x02, 0x11, settingsByte]` |
| `setFanSpeedPercent(p)` | `[0x07, 0x0E, modeId, p / 5, tempByte, hours, minutes, 0x00]` |

## 13. Reserved and Unknown Areas

These items are present but not fully documented. Do not block the first implementation on them.

### BedJet 3

- `SET_STEP` (`0x04`)
- `SET_HACKS` (`0x05`)
- `STATUS` (`0x06`)
- `SET_BIO` (`0x40`)
- `DEBUG_ON` (`0x40`)
- `DEBUG_OFF` (`0x41`)
- `CONNECTION_TEST` (`0x42`)
- `UPDATE_FIRMWARE` (`0x43`)
- `NOTIFY_ACK` (`0x52`)
- Status read reserved bytes: `0`, `1`, `3`, `4`, `5`, `10`
- Status notification reserved bytes: `0-3`, `19`
- `SSID` characteristic
- `Password` characteristic
- `Biodata` characteristic `00002005-bed0-0080-aa55-4265644a6574`

### BedJet V2

- Memory activation is not documented
- Biorhythm activation is not documented
- Explicit runtime write is not documented
- Some notification bytes remain only partially understood

## 14. Minimal Validation Checklist

An implementation is complete for first-stage control when all of the following pass on hardware:

1. Scan discovers both model families.
2. Connect identifies `BedJet 3` vs `BedJet V2` correctly.
3. Live state subscription yields stable normalized state.
4. `setMode()` works for all supported modes.
5. `setFanSpeedPercent()` works across the full supported range.
6. `setTargetTemperatureC()` writes the requested setpoint.
7. `setLedEnabled()` and `setBeepsMuted()` persist correctly.
8. `syncClock()` works on `BedJet 3`.
9. `setRuntimeRemaining()` works on `BedJet 3`.
10. `readMetadata()` returns device name, firmware, and preset names on `BedJet 3`.

## Acknowledgments & References

* [Home Assistant BedJet Integration (ha-bedjet)](https://github.com/natekspencer/ha-bedjet) — An excellent Home Assistant integration by natekspencer that served as an invaluable reference for decoding parts of the BedJet Bluetooth protocol.
