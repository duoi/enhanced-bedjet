# BedJet System Architecture

## 1. Scope

This document defines the system architecture for the BedJet app: a hub server that maintains the BLE connection to the BedJet device, and mobile client apps that communicate with the hub over the local network.

Related documents:

- `BEDJET_BLE_API_REFERENCE.md`: BLE protocol, command set, packet formats, state model
- `BEDJET_QUIRKS.md`: device-level quirks and required workarounds

## 2. System Overview

```text
Phone A  ──┐                              ┌── BedJet
            ├── Wi-Fi ── Hub ──── BLE ────┤
Phone B  ──┘            │                 └── (single connection)
                        │
                   ┌────┴────┐
                   │ FastAPI │
                   │ + bleak │
                   │ + SQLite│
                   │ + async │
                   │scheduler│
                   └─────────┘
                   (Ubuntu Server, mini PC)
```

The hub is the only BLE client. It owns the device connection, serializes commands, and fans out live state to all connected phone clients. Phone apps are pure network clients with no BLE dependency.

## 3. Technology Stack

| Component | Technology | Purpose |
| --- | --- | --- |
| Hub BLE layer | Python 3.12 + `bleak` | BLE scanning, connection, GATT operations |
| Hub API | FastAPI + `uvicorn` | REST endpoints + WebSocket for live state |
| Hub storage | SQLite via `aiosqlite` | Biorhythm programs, preferences, device metadata |
| Hub scheduler | `asyncio` tasks | Biorhythm step execution, clock sync |
| Phone app | React Native + Expo | UI client over HTTP + WebSocket |

## 4. Hub Server

### 4.1 Process Model

The hub runs as a single `asyncio` process with three concurrent subsystems:

1. **BLE manager**: maintains the device connection, subscribes to notifications, executes commands.
2. **API server**: serves REST and WebSocket endpoints for phone clients.
3. **Scheduler**: manages active biorhythm sequence execution.

All three share the same event loop. The BLE manager is the single owner of the device connection. The API server and scheduler submit commands to the BLE manager through an internal async command queue.

### 4.2 BLE Manager

Implements the protocol defined in `BEDJET_BLE_API_REFERENCE.md`.

Responsibilities:

- Scan for BedJet devices on startup.
- Connect to the configured device.
- Subscribe to status notifications and maintain the current normalized device state in memory.
- Apply jitter suppression per section `10.8` of the protocol spec.
- Expose an internal async interface for submitting commands (used by the API server and scheduler).
- Serialize all BLE writes through a command queue.
- Reconnect automatically on unexpected disconnect with exponential backoff (initial delay `2` seconds, max delay `30` seconds).
- Sync the device clock on every successful connect.
- Detect stale data after `60` seconds without a notification and attempt reconnect.

Internal interface:

```python
class BleManager:
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def get_state(self) -> DeviceState: ...
    def get_metadata(self) -> DeviceMetadata: ...
    def subscribe(self, callback: Callable[[DeviceState], None]) -> Callable[[], None]: ...
    async def set_mode(self, mode: OperatingMode) -> None: ...
    async def set_fan_speed(self, percent: int) -> None: ...
    async def set_temperature(self, celsius: float) -> None: ...
    async def set_led(self, enabled: bool) -> None: ...
    async def set_muted(self, muted: bool) -> None: ...
    async def sync_clock(self) -> None: ...
    async def set_runtime(self, hours: int, minutes: int) -> None: ...
    async def activate_memory(self, slot: int) -> None: ...
    async def activate_biorhythm(self, slot: int) -> None: ...
```

### 4.3 API Server

#### 4.3.1 REST Endpoints

All endpoints return JSON. All request bodies are JSON.

**Device state and metadata:**

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/device` | Current device state + metadata + connection status |

Response:

```json
{
  "connected": true,
  "metadata": {
    "address": "AA:BB:CC:DD:EE:FF",
    "name": "BedJet",
    "model": "v3",
    "firmwareVersion": "1.2.3",
    "memoryNames": ["Sleep", "Cool Down", null],
    "biorhythmNames": ["Night", null, null]
  },
  "state": {
    "mode": "heat",
    "currentTemperatureC": 36.5,
    "targetTemperatureC": 38.0,
    "ambientTemperatureC": 22.0,
    "fanSpeedPercent": 60,
    "runtimeRemainingSeconds": 1800,
    "runEndTime": "2026-04-06T03:30:00Z",
    "maximumRuntimeSeconds": 14400,
    "turboTimeSeconds": 0,
    "minTemperatureC": 19.0,
    "maxTemperatureC": 43.0,
    "ledEnabled": true,
    "beepsMuted": false,
    "dualZone": false,
    "unitsSetup": true,
    "connectionTestPassed": true,
    "bioSequenceStep": null,
    "notification": "none",
    "shutdownReason": 0,
    "updatePhase": null
  }
}
```

**Device commands:**

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| `POST` | `/api/device/mode` | `{"mode": "heat"}` | Set operating mode |
| `POST` | `/api/device/fan` | `{"percent": 60}` | Set fan speed |
| `POST` | `/api/device/temperature` | `{"celsius": 38.0}` | Set target temperature |
| `POST` | `/api/device/led` | `{"enabled": true}` | Set LED state |
| `POST` | `/api/device/mute` | `{"muted": false}` | Set mute state |
| `POST` | `/api/device/clock/sync` | none | Sync device clock to hub system time |
| `POST` | `/api/device/runtime` | `{"hours": 2, "minutes": 30}` | Set runtime remaining |
| `POST` | `/api/device/memory/{slot}` | none | Activate memory preset (slot `1-3`) |
| `POST` | `/api/device/biorhythm/{slot}` | none | Activate device biorhythm preset (slot `1-3`) |

All command endpoints return:

```json
{"ok": true}
```

Or on error:

```json
{"ok": false, "error": "description"}
```

**Biorhythm programs (user-defined):**

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| `GET` | `/api/programs` | none | List all saved biorhythm programs |
| `POST` | `/api/programs` | program object | Create a new program |
| `GET` | `/api/programs/{id}` | none | Get a single program |
| `PUT` | `/api/programs/{id}` | program object | Update a program |
| `DELETE` | `/api/programs/{id}` | none | Delete a program |
| `POST` | `/api/programs/{id}/activate` | `{"startTime": "22:00"}` | Activate with delta logic |
| `POST` | `/api/programs/stop` | none | Stop the active program |
| `GET` | `/api/programs/active` | none | Get the currently active program and its progress |

Program object:

```json
{
  "id": "uuid",
  "name": "Night Routine",
  "steps": [
    {
      "mode": "heat",
      "temperatureC": 38.0,
      "fanSpeedPercent": 60,
      "durationMinutes": 30
    },
    {
      "mode": "cool",
      "temperatureC": 22.0,
      "fanSpeedPercent": 40,
      "durationMinutes": 120
    },
    {
      "mode": "standby",
      "temperatureC": null,
      "fanSpeedPercent": null,
      "durationMinutes": 0
    }
  ],
  "createdAt": "2026-04-05T20:00:00Z",
  "updatedAt": "2026-04-05T20:00:00Z"
}
```

Active program response:

```json
{
  "programId": "uuid",
  "programName": "Night Routine",
  "startTime": "2026-04-05T22:00:00Z",
  "currentStepIndex": 1,
  "stepStartedAt": "2026-04-05T22:30:00Z",
  "stepEndsAt": "2026-04-06T00:30:00Z",
  "totalSteps": 3
}
```

**Preferences:**

| Method | Path | Body | Description |
| --- | --- | --- | --- |
| `GET` | `/api/preferences` | none | Get all preferences |
| `PUT` | `/api/preferences` | preferences object | Update preferences |

Preferences object:

```json
{
  "temperatureUnit": "celsius",
  "defaultFanSpeedPercent": 50,
  "autoSyncClock": true
}
```

#### 4.3.2 WebSocket

| Path | Direction | Description |
| --- | --- | --- |
| `/ws` | server to client | Live device state updates |

On connect, the server immediately sends the current device state. After that, it pushes a new state message whenever the device state changes (after jitter suppression).

Message format:

```json
{
  "type": "state",
  "connected": true,
  "state": { ... },
  "activeProgram": { ... } | null
}
```

If the BLE connection drops:

```json
{
  "type": "connection",
  "connected": false
}
```

On reconnect:

```json
{
  "type": "connection",
  "connected": true
}
```

Followed immediately by a full state message.

### 4.4 Storage Schema

SQLite database at a configurable path (default: `data/bedjet.db`).

#### `programs` table

| Column | Type | Description |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | UUID |
| `name` | `TEXT NOT NULL` | Display name |
| `created_at` | `TEXT NOT NULL` | ISO 8601 |
| `updated_at` | `TEXT NOT NULL` | ISO 8601 |

#### `program_steps` table

| Column | Type | Description |
| --- | --- | --- |
| `id` | `TEXT PRIMARY KEY` | UUID |
| `program_id` | `TEXT NOT NULL` | FK to `programs.id` |
| `position` | `INTEGER NOT NULL` | Step order (0-indexed) |
| `mode` | `TEXT NOT NULL` | Operating mode name |
| `temperature_c` | `REAL` | Target temperature, nullable for standby |
| `fan_speed_percent` | `INTEGER` | Fan speed, nullable for standby |
| `duration_minutes` | `INTEGER NOT NULL` | Step duration |

#### `preferences` table

| Column | Type | Description |
| --- | --- | --- |
| `key` | `TEXT PRIMARY KEY` | Preference key |
| `value` | `TEXT NOT NULL` | JSON-encoded value |

#### `active_sequence` table

| Column | Type | Description |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY` | Always `1` (singleton row) |
| `program_id` | `TEXT NOT NULL` | FK to `programs.id` |
| `start_time` | `TEXT NOT NULL` | ISO 8601, the nominal start time |
| `current_step_index` | `INTEGER NOT NULL` | Currently executing step |
| `started_at` | `TEXT NOT NULL` | ISO 8601, when the hub started executing |

This table has at most one row. It is written when a program is activated and deleted when the program completes or is stopped. On hub restart, if this row exists, the scheduler recomputes the delta and resumes from the correct step.

### 4.5 Scheduler

The scheduler manages active biorhythm program execution.

#### Activation flow

1. Client calls `POST /api/programs/{id}/activate` with a `startTime`.
2. The hub computes the delta between `now` and `startTime` using the logic from `BEDJET_QUIRKS.md` section `2.3`.
3. If the entire program has elapsed, return an error.
4. Seek to the active step and compute its remaining duration.
5. Apply the active step's mode, temperature, and fan speed to the device via the BLE manager.
6. Set the device runtime to the active step's remaining duration (BedJet 3 only).
7. Write the `active_sequence` row to the database.
8. Schedule an `asyncio` task that sleeps until the active step ends, then advances to the next step.

#### Step advancement

When a step's timer fires:

1. Load the next step from the program.
2. Apply its mode, temperature, and fan speed.
3. Set the runtime to the step's full duration.
4. Update `current_step_index` in `active_sequence`.
5. Schedule the next timer.
6. Push state to all WebSocket clients.

When the final step completes:

1. If the final step's mode is not `STANDBY`, set the device to `STANDBY`.
2. Delete the `active_sequence` row.
3. Push state to all WebSocket clients.

#### Hub restart recovery

On startup, if an `active_sequence` row exists:

1. Load the program and its steps.
2. Recompute the delta from `start_time` to `now`.
3. Seek to the correct step.
4. Apply and schedule as if the program was just activated.

#### Stop

When `POST /api/programs/stop` is called:

1. Cancel the active timer.
2. Delete the `active_sequence` row.
3. Do not change the device mode (the user may want to keep the current state).

### 4.6 Hub Startup Sequence

1. Initialize SQLite database and run migrations if needed.
2. Start the BLE manager.
3. Scan for the BedJet device. If not found, retry with exponential backoff.
4. Connect to the device and sync the clock.
5. Check for an `active_sequence` row and resume if present.
6. Start the FastAPI server.

### 4.7 Hub Configuration

Minimal configuration via environment variables or a config file:

| Key | Default | Description |
| --- | --- | --- |
| `BEDJET_ADDRESS` | auto-discover | BLE MAC address of the BedJet device |
| `HUB_HOST` | `0.0.0.0` | API listen address |
| `HUB_PORT` | `8265` | API listen port |
| `DB_PATH` | `data/bedjet.db` | SQLite database path |

If `BEDJET_ADDRESS` is not set, the hub scans for the first discoverable BedJet device and uses that.

## 5. Phone App

### 5.1 Architecture

The phone app is a React Native + Expo application. It has no BLE dependency. All device interaction goes through the hub API.

### 5.2 Network Layer

The app connects to the hub at a configured address (e.g. `http://192.168.1.50:8265`).

Two connections:

1. **HTTP client**: for REST calls (commands, program CRUD, preferences).
2. **WebSocket client**: for live state updates from `/ws`.

The WebSocket connection should be established on app launch and maintained while the app is in the foreground. On disconnect, reconnect with exponential backoff. On app background, close the WebSocket. On app foreground, re-establish.

### 5.3 State Management

The app maintains two kinds of state:

1. **Device state**: received exclusively from the WebSocket. Never cached to disk. Always live from the hub.
2. **UI state**: local to the app (selected screen, pending form values, animation state). Standard React state management.

The hub is the single source of truth for device state, program definitions, and preferences. The phone app does not persist any of these locally.

### 5.4 Hub Discovery

For initial setup, the app needs to know the hub's IP address. Options in order of preference:

1. **mDNS/Bonjour**: the hub advertises itself as `_bedjet._tcp.local`. The app discovers it automatically using `react-native-zeroconf`.
2. **Manual entry**: the user types the hub IP address in a settings screen.
3. **QR code**: the hub displays a QR code in its terminal on startup containing the connection URL. The app scans it.

Implement option `2` first. Add `1` as an enhancement.

### 5.5 Required Screens

| Screen | Purpose |
| --- | --- |
| Setup | Enter hub address, verify connection |
| Dashboard | Current device state, quick controls (mode, temperature, fan) |
| Controls | Full control surface (all modes, fan slider, temperature slider, LED, mute, runtime) |
| Programs | List, create, edit, delete biorhythm programs |
| Program Editor | Step-by-step editor for a biorhythm program |
| Active Program | Live view of the running program with timeline and current step |
| Preferences | Temperature unit, default fan speed, hub connection settings |

### 5.6 API Client Interface

The phone app should implement a typed client that wraps all hub API calls.

```typescript
interface HubClient {
  getDevice(): Promise<DeviceResponse>;
  setMode(mode: string): Promise<void>;
  setFanSpeed(percent: number): Promise<void>;
  setTemperature(celsius: number): Promise<void>;
  setLed(enabled: boolean): Promise<void>;
  setMute(muted: boolean): Promise<void>;
  syncClock(): Promise<void>;
  setRuntime(hours: number, minutes: number): Promise<void>;
  activateMemory(slot: number): Promise<void>;
  activateDeviceBiorhythm(slot: number): Promise<void>;

  getPrograms(): Promise<Program[]>;
  getProgram(id: string): Promise<Program>;
  createProgram(program: CreateProgramRequest): Promise<Program>;
  updateProgram(id: string, program: UpdateProgramRequest): Promise<Program>;
  deleteProgram(id: string): Promise<void>;
  activateProgram(id: string, startTime: string): Promise<void>;
  stopProgram(): Promise<void>;
  getActiveProgram(): Promise<ActiveProgram | null>;

  getPreferences(): Promise<Preferences>;
  updatePreferences(prefs: Partial<Preferences>): Promise<Preferences>;

  connectWebSocket(onState: (msg: StateMessage) => void): () => void;
}
```

## 6. Security

This system runs on a local network with no internet exposure. Security is minimal but not zero.

- The hub API has no authentication by default.
- The hub should bind to the local network interface only.
- If the network is untrusted, add a shared secret as a bearer token in the hub config and validate it on every request.
- Do not expose the hub port to the internet.

## 7. Deployment

### Hub

1. Install Python 3.12+ on the Ubuntu Server mini PC.
2. Ensure the `bluetooth` service is running (`sudo systemctl status bluetooth`).
3. Install dependencies: `pip install bleak fastapi uvicorn aiosqlite`.
4. Run the hub: `python -m bedjet_hub`.
5. Optionally configure as a `systemd` service for auto-start on boot.

### Phone App

1. Build with Expo: `npx expo build`.
2. Install on devices via Expo Go (development) or a local build (production).
3. On first launch, enter the hub IP address.

## 8. Project Structure

```text
bedjet-app/
├── BEDJET_BLE_API_REFERENCE.md
├── BEDJET_QUIRKS.md
├── BEDJET_SYSTEM_ARCHITECTURE.md
├── hub/
│   ├── pyproject.toml
│   ├── bedjet_hub/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── ble/
│   │   │   ├── __init__.py
│   │   │   ├── manager.py
│   │   │   ├── protocol_v3.py
│   │   │   ├── protocol_v2.py
│   │   │   ├── state.py
│   │   │   └── const.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── server.py
│   │   │   ├── routes_device.py
│   │   │   ├── routes_programs.py
│   │   │   ├── routes_preferences.py
│   │   │   └── websocket.py
│   │   ├── scheduler/
│   │   │   ├── __init__.py
│   │   │   └── runner.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py
│   │   │   └── migrations.py
│   │   └── config.py
│   └── data/
│       └── bedjet.db
└── app/
    ├── package.json
    ├── app.json
    ├── src/
    │   ├── api/
    │   │   ├── client.ts
    │   │   └── types.ts
    │   ├── hooks/
    │   │   ├── useDeviceState.ts
    │   │   └── useWebSocket.ts
    │   ├── screens/
    │   │   ├── SetupScreen.tsx
    │   │   ├── DashboardScreen.tsx
    │   │   ├── ControlsScreen.tsx
    │   │   ├── ProgramsScreen.tsx
    │   │   ├── ProgramEditorScreen.tsx
    │   │   ├── ActiveProgramScreen.tsx
    │   │   └── PreferencesScreen.tsx
    │   └── components/
    │       └── ...
    └── ...
```

## 9. Implementation Order

Build in this order to validate each layer before building on top of it.

### Phase 1: Hub BLE layer

Implement `ble/manager.py`, `ble/protocol_v3.py`, `ble/protocol_v2.py`, `ble/state.py`, `ble/const.py` using the protocol spec. Validate by running on the mini PC and confirming:

- Device discovery
- Connect and subscribe
- Live state printing to terminal
- Mode, fan, and temperature commands

### Phase 2: Hub API

Add FastAPI with the device endpoints and WebSocket. Validate by:

- Hitting endpoints with `curl`
- Connecting to the WebSocket with `websocat` and seeing live state

### Phase 3: Hub storage and programs

Add SQLite, program CRUD endpoints, and the scheduler. Validate by:

- Creating a program via the API
- Activating it and observing step transitions

### Phase 4: Phone app shell

Scaffold the React Native app with Expo. Implement the hub client, WebSocket hook, and the setup + dashboard screens. Validate by:

- Seeing live device state on the phone
- Sending mode/fan/temperature commands from the phone

### Phase 5: Phone app controls and programs

Build out the remaining screens: full controls, program list, program editor, active program view, preferences.

### Phase 6: Polish

- mDNS hub discovery
- Hub `systemd` service
- Error handling and retry UI
- Animations and transitions
