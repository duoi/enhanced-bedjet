# Webapp, bluetooth hub and MCP tools for BedJet

<img width="1953" height="1258" alt="Screenshots of three screens within the new webapp" src="https://github.com/user-attachments/assets/0de18672-45f2-41ee-a710-cd9ed069d138" />

A self-hosted BLE-to-HTTP bridge and mobile web app for controlling [BedJet](https://bedjet.com) sleep climate devices from any device on your local network.

## Overview

The BedJet's native app relies on direct Bluetooth pairing with a phone, limiting control to one device within BLE range. This project replaces that constraint with a two-part architecture:

- **Hub** (`hub/`) — Two Python daemons: one that maintains the BLE connection to the BedJet (communicating over UNIX domain sockets), and a web server that exposes a REST + WebSocket API over your LAN. Runs on a Raspberry Pi or any Linux host with a Bluetooth adapter.
- **App** (`app/`) — A React (Vite) progressive web app that connects to the hub. Installable on any phone's home screen as a PWA.

```
Phone / Tablet                 Raspberry Pi              BedJet
┌────────────┐    HTTP/WS     ┌──────────┐    BLE      ┌────────┐
│  React PWA │ ◄────────────► │   Hub    │ ◄──────────► │ Device │
└────────────┘   (LAN)        └──────────┘              └────────┘
```

## Features

- **Temperature arc dial** with touch/mouse dragging and quick-select presets
- **Mode selector** — Heat, Cool, Dry, Turbo, Extended Heat
- **Fan speed slider** with named presets (Whisper → Turbo)
- **Biorhythm programs** — multi-step temperature sequences with scheduling, day-of-week selection, and duration/until timing
- **Telemetry tracking** — automatically logs mode, temperature, and fan speed to a local SQLite database every 5 minutes
- **Settings** — LED ring, mute, clock sync, memory/biorhythm preset activation
- **Live state** via WebSocket — temperature, fan, mode, runtime countdown
- **Optimistic UI** — instant feedback with convergence checks against the device
- **Dual protocol** — supports both BedJet V2 (ISSC) and V3 (Nordic) BLE protocols
- **Auto-reconnect** with exponential backoff
- **mDNS discovery** for zero-config hub finding
- **Offline-capable** PWA with service worker caching
- **MCP server** (`mcp/`) — stdio proxy for AI agent integration (zero dependencies)

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| Hub       | Python 3.11+, Bluetooth adapter, Linux (BlueZ) |
| App       | Node.js 18+ (dev only; built app is static) |

## Quick Start

### Hub

```bash
cd hub
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: set the BedJet's BLE MAC address (otherwise auto-scans)
export BEDJET_ADDRESS="AA:BB:CC:DD:EE:FF"

# Start the BLE connection worker
python -m bedjet_hub.ble_daemon &

# Start the Web API / Hub
python -m bedjet_hub
```

The hub starts on `0.0.0.0:8265` by default. Configuration is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDJET_ADDRESS` | *(auto-scan)* | BLE MAC address of the BedJet |
| `HUB_HOST` | `0.0.0.0` | Network interface to bind |
| `HUB_PORT` | `8265` | HTTP/WebSocket port |
| `DB_PATH` | `data/bedjet.db` | SQLite database path |
| `CORS_ORIGINS` | `localhost:8678` | Comma-separated list of allowed Origins for the UI (e.g., `http://192.168.1.50:8678`). Replace with your IP/Domain for security. |

For production deployment, use the provided systemd templates (`hub/bedjet-ble.service` and `hub/bedjet-hub.service`). The decoupled services ensure that restarting the API does not drop the physical Bluetooth connection.

### App

```bash
cd app
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/ws` to `localhost:8265`, so the app auto-connects to a local hub. For production, build and serve the static files:

```bash
npm run build
# Serve app/dist/ with any static file server
```

On first launch, the app probes for a proxy connection. If unavailable, it shows a setup screen where you enter the hub's IP address.

## Project Structure

```
├── app/                    # React (Vite) progressive web app
│   ├── src/
│   │   ├── App.jsx         # Root shell with tab navigation
│   │   ├── ControlScreen   # Temperature dial, mode, fan, runtime
│   │   ├── ProgramsScreen  # Biorhythm program CRUD + editor
│   │   ├── SettingsScreen  # Device info, LED/mute, preferences
│   │   ├── SetupScreen     # Hub connection setup
│   │   ├── TempArc         # Circular temperature slider
│   │   ├── RuntimeEditor   # Hours/minutes runtime input
│   │   ├── hub.jsx         # React context (WebSocket + state)
│   │   ├── api.js          # REST/WS client
│   │   ├── utils.js        # Temp conversion, mode constants
│   │   └── timeUtils.js    # Duration/time formatting
│   └── public/             # PWA manifest, icons, service worker
├── hub/                    # Python hub daemons
│   ├── bedjet_hub/
│   │   ├── api/            # FastAPI routes + WebSocket
│   │   ├── ble/            # BLE protocol (V2 + V3), IPC server/client
│   │   ├── ble_daemon.py   # Headless Bluetooth worker process
│   │   ├── db/             # SQLite (programs, preferences)
│   │   └── scheduler/      # Biorhythm program executor
│   ├── tests/              # pytest test suite
│   ├── bedjet-ble.service  # systemd service for Bluetooth connection
│   ├── bedjet-hub.service  # systemd service for Web API
│   └── pyproject.toml
├── mcp/                    # AI agent integration
│   ├── server.py           # MCP stdio proxy (zero dependencies)
│   └── SKILL.md            # Hermes Agent skill definition
├── docs/                   # BedJet protocol documentation
│   ├── BEDJET_BLE_API_REFERENCE.md
│   ├── BEDJET_SYSTEM_ARCHITECTURE.md
│   └── BEDJET_QUIRKS.md
└── AGENTS.md               # Autonomous agent setup guide
```

## API Reference

### REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/device` | Device state, metadata, connection status |
| POST | `/api/device/mode` | Set operating mode |
| POST | `/api/device/fan` | Set fan speed (5–100%) |
| POST | `/api/device/temperature` | Set target temperature (°C) |
| POST | `/api/device/led` | Toggle LED ring |
| POST | `/api/device/mute` | Toggle beep mute |
| POST | `/api/device/clock/sync` | Sync device clock to hub time |
| POST | `/api/device/runtime` | Set runtime (hours + minutes) |
| POST | `/api/device/memory/:slot` | Activate memory preset (1–3) |
| POST | `/api/device/biorhythm/:slot` | Activate device biorhythm (1–3) |
| GET | `/api/programs` | List all programs |
| POST | `/api/programs` | Create a program |
| GET | `/api/programs/:id` | Get a program |
| PUT | `/api/programs/:id` | Update a program |
| DELETE | `/api/programs/:id` | Delete a program |
| POST | `/api/programs/:id/activate` | Activate a program |
| POST | `/api/programs/stop` | Stop the active program |
| GET | `/api/programs/active` | Get active program status |
| GET | `/api/preferences` | Get user preferences |
| PUT | `/api/preferences` | Update user preferences |

### WebSocket

Connect to `/ws` for real-time device state. Messages are JSON with a `type` field:

- `state` — full device state snapshot (mode, temps, fan, runtime, active program)
- `connection` — BLE connection status change
- `ping` — keepalive (sent every 30s of inactivity)

## Testing

```bash
# Hub tests
cd hub
pip install -e ".[dev]"
pytest

# App tests
cd app
npm test
```

## MCP Server

The `mcp/` directory contains a stdio MCP server that exposes the BedJet Hub API as AI agent tools. Zero dependencies beyond Python 3 — it proxies MCP protocol calls to the hub's REST API at `localhost:8265`.

### With Hermes Agent

```bash
hermes mcp add bedjet --command python3 --args /opt/bedjet/hub/mcp/server.py
```

Tools register as `mcp_bedjet_*` (e.g. `mcp_bedjet_get_device_status`, `mcp_bedjet_set_target_temperature`). See `mcp/SKILL.md` for the full tool list and usage guidance.

### With Any MCP Client

```yaml
mcp_servers:
  bedjet:
    command: python3
    args: ["/path/to/mcp/server.py"]
```

The hub must be running first (`systemctl start bedjet-hub.service`).

## Documentation

Protocol reverse-engineering notes and architecture documentation are in the `docs/` directory:

- **[BLE API Reference](docs/BEDJET_BLE_API_REFERENCE.md)** — GATT services, characteristics, command encoding, status notification parsing for V2 and V3
- **[System Architecture](docs/BEDJET_SYSTEM_ARCHITECTURE.md)** — Hub design, API spec, WebSocket protocol, scheduler logic
- **[Known Quirks](docs/BEDJET_QUIRKS.md)** — Protocol edge cases, timing constraints, and device-specific behaviors
- **[AGENTS.md](AGENTS.md)** — Step-by-step setup guide for autonomous AI agents

## License

[GNU General Public License v3.0](LICENSE)
