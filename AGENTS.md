# BedJet Hub — Autonomous Agent Setup Guide

This guide is written for an AI agent (or a human) to set up the entire BedJet Hub system from scratch on a fresh Linux host with Bluetooth. Follow steps in order. Each section includes verification commands.

## What You're Building

A two-part system that replaces the BedJet phone app:

1. **Hub daemon** — Python process that connects to the BedJet via BLE and exposes a REST/WebSocket API on the LAN
2. **Web UI** — React PWA that talks to the hub, installable on any phone

```
Phone/PWA  ──HTTP/WS──>  Hub (Pi/Linux)  ──BLE──>  BedJet Device
```

## Prerequisites

- Linux host with Bluetooth adapter (Raspberry Pi 3/4/5, any Linux box with BT)
- Python 3.11+
- Node.js 18+ (for building the web UI)
- BlueZ installed and running (`bluetoothctl` should work)
- `git` available

## Step 1: Clone and Navigate

```bash
cd /opt
git clone <repo-url> bedjet
cd bedjet/hub
```

Verify:
```bash
ls hub/pyproject.toml app/package.json mcp/server.py
# All three should exist
```

## Step 2: Python Virtual Environment

```bash
cd /opt/bedjet/hub
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs: `bleak`, `fastapi`, `uvicorn`, `aiosqlite`, `zeroconf`.

Verify:
```bash
.venv/bin/python -c "import bleak, fastapi, uvicorn, aiosqlite, zeroconf; print('All imports OK')"
```

## Step 3: Find Your BedJet's BLE MAC Address

```bash
bluetoothctl scan on
# Wait 10-15 seconds, look for "BedJet" or "BEDJET3"
# Note the MAC address (e.g., D4:8C:49:B7:11:F2)
bluetoothctl scan off
```

If you already know the MAC, skip the scan.

## Step 4: Configure Environment

Create `/opt/bedjet/hub/.env`:
```bash
echo 'BEDJET_ADDRESS=<YOUR_MAC_HERE>' > /opt/bedjet/hub/.env
```

Example:
```bash
echo 'BEDJET_ADDRESS=D4:8C:49:B7:11:F2' > /opt/bedjet/hub/.env
```

This file is loaded by systemd via `EnvironmentFile`. Do NOT commit it to version control.

Verify:
```bash
cat /opt/bedjet/hub/.env
# Should show BEDJET_ADDRESS=<mac>
```

## Step 5: Test the Hub Manually

Before setting up systemd, verify the hub can connect:

```bash
cd /opt/bedjet/hub
source .venv/bin/activate
python -m bedjet_hub
```

Watch for:
- `Starting on 0.0.0.0:8265` — server is up
- BLE connection messages — should connect to the BedJet

Test from another terminal:
```bash
curl http://localhost:8265/api/device | python3 -m json.tool
```

If the device status shows connection info, it's working. Stop the manual run with Ctrl+C.

## Step 6: Install Systemd Services

### Hub Service

The files are at `/opt/bedjet/hub/bedjet-ble.service` and `/opt/bedjet/hub/bedjet-hub.service`. Install them:

```bash
cp /opt/bedjet/hub/bedjet-ble.service /etc/systemd/system/
cp /opt/bedjet/hub/bedjet-hub.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bedjet-ble.service bedjet-hub.service
systemctl start bedjet-ble.service
systemctl start bedjet-hub.service
```

Verify:
```bash
systemctl status bedjet-ble.service bedjet-hub.service
# Both should show "active (running)"
curl http://localhost:8265/api/device
```

### Web UI Service (Optional)

If you want the web interface accessible on the LAN:

```bash
cd /opt/bedjet/hub/app
npm install
npm run build
```

Install the UI service:
```bash
cp /opt/bedjet/hub/app/bedjet-ui.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bedjet-ui.service
systemctl start bedjet-ui.service
```

Verify:
```bash
systemctl status bedjet-ui.service
# Should show "active (running)"
# Access at http://<host-ip>:8678
```

## Step 7: Configure MCP Server (for Hermes Agent)

If using Hermes Agent, you need two things: the MCP Python SDK and the server registration.

### 7a: Install the MCP SDK

Hermes's native MCP client requires the `mcp` Python package:

```bash
pip install mcp
# or, if using uv:
uv pip install mcp
```

Without this, Hermes silently skips MCP tool discovery at startup.

### 7b: Register the BedJet MCP Server

Use the Hermes CLI (preferred over manual YAML editing):

```bash
hermes mcp add bedjet --command python3 --args /opt/bedjet/hub/mcp/server.py
```

This writes to `~/.hermes/config.yaml` under the `mcp_servers` key. The MCP server is a stdio proxy with zero dependencies beyond Python 3 — it connects to the hub at `localhost:8265`.

### 7c: Restart Hermes

MCP servers are discovered at startup only — there is no hot-reload. After adding the server:

```bash
# If running interactively: exit and restart
hermes

# If running as gateway service:
hermes gateway restart
```

On startup, Hermes will:
1. Launch `python3 /opt/bedjet/hub/mcp/server.py` as a subprocess
2. Discover available tools via MCP protocol
3. Register them with the prefix `mcp_bedjet_*`
4. Inject them into all platform toolsets automatically

### 7d: Install the Skill (Optional)

If the SKILL.md is published to a skill hub:

```bash
hermes skills install bedjet-mcp
```

Or install manually by copying `mcp/SKILL.md` to `~/.hermes/skills/bedjet-mcp/SKILL.md`.

The skill gives the agent context on when and how to use the tools, known quirks, and troubleshooting. Without it, the tools work but the agent has no domain knowledge.

### Verify

```bash
# Check MCP server is registered
hermes mcp list

# Test connection
hermes mcp test bedjet

# In an active session, ask:
# "what's the bedjet status?"
# Should call mcp_bedjet_get_device_status
```

### Troubleshooting Hermes Integration

- **"MCP SDK not available"** → `pip install mcp`
- **"No MCP servers configured"** → Check `~/.hermes/config.yaml` has `mcp_servers:` with `bedjet:` entry
- **"Failed to connect to MCP server 'bedjet'"** → Verify hub is running: `curl http://localhost:8265/api/device`
- **Tools not appearing** → Restart the agent (no hot-reload). Check `hermes mcp test bedjet`
- **Connection keeps dropping** → Hermes retries 5 times with exponential backoff (up to 60s). If the hub is down, it gives up until next restart

## Step 8: Firewall (if needed)

If accessing from other devices on the LAN:

```bash
# Hub API
ufw allow 8265/tcp

# Web UI (if using bedjet-ui.service)
ufw allow 8678/tcp

ufw reload
```

## Troubleshooting

### Hub won't start

Check logs:
```bash
journalctl -u bedjet-hub.service -n 50 --no-pager
```

Common causes:
- BLE adapter not available: `hciconfig` or `bluetoothctl list`
- MAC address wrong: re-scan with `bluetoothctl scan on`
- Port 8265 in use: `ss -tlnp | grep 8265`

### Hub starts but can't connect to BedJet

1. Make sure no phone app is connected to the BedJet simultaneously — BLE is single-client
2. Check if the BedJet is powered on
3. Try `bluetoothctl disconnect <MAC>` if there's a stale connection, then restart the hub

### Zombie BLE connection

**Symptom:** Status shows connected, commands do nothing, or hub fails to start with "Address already in use".

**Fix:** This bug was fundamentally patched in Hub v0.3.0 by decoupling the Bluetooth connection into a standalone background worker (`bedjet-ble.service`). If you still encounter it because you are running the daemon manually in a terminal and forcefully killed it:

```bash
bluetoothctl disconnect <MAC>
systemctl restart bedjet-ble.service
systemctl restart bedjet-hub.service
```

### MCP tools not appearing in Hermes

1. Check `~/.hermes/config.yaml` — the server entry must be under `mcp_servers`
2. Restart Hermes Agent (no hot-reload for MCP servers)
3. Check `python3 /opt/bedjet/hub/mcp/server.py` runs without errors
4. Verify the hub is running: `curl http://localhost:8265/api/device`

### Web UI can't find hub

The UI probes for the hub on load. If it shows the setup screen:
1. Enter the hub's IP address manually (e.g., `192.168.1.50:8265`)
2. Or ensure mDNS is working on the LAN (`avahi-browse -a` to check)

## File Layout

```
/opt/bedjet/hub/
├── .env                          # BEDJET_ADDRESS=<mac> (DO NOT COMMIT)
├── .venv/                        # Python virtual environment
├── hub/
│   ├── bedjet_hub/
│   │   ├── __main__.py           # Web API entry point (python -m bedjet_hub)
│   │   ├── ble_daemon.py         # BLE worker entry point
│   │   ├── config.py             # Environment variable config
│   │   ├── api/                  # FastAPI routes + WebSocket
│   │   ├── ble/                  # BLE protocol V2/V3, connection manager, IPC
│   │   ├── db/                   # SQLite database (programs, prefs)
│   │   └── scheduler/            # Biorhythm program executor
│   ├── tests/                    # pytest suite
│   └── pyproject.toml            # Dependencies
├── app/                          # React PWA (Vite)
│   ├── src/                      # UI components
│   ├── public/                   # PWA manifest, icons, service worker
│   └── bedjet-ui.service         # systemd unit for web UI
├── mcp/
│   ├── server.py                 # MCP stdio proxy (zero deps)
│   └── SKILL.md                  # Hermes Agent skill definition
├── bedjet-ble.service            # systemd unit for bluetooth worker
├── bedjet-hub.service            # systemd unit for web API
└── AGENTS.md                     # This file
```

## Key Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDJET_ADDRESS` | *(auto-scan)* | BLE MAC address of the BedJet |
| `HUB_HOST` | `0.0.0.0` | Network interface to bind |
| `HUB_PORT` | `8265` | HTTP/WebSocket port |
| `DB_PATH` | `data/bedjet.db` | SQLite database path |
| `CORS_ORIGINS` | `localhost:8678`| Comma-separated list of allowed Origins. Add your UI domain/IP (e.g. `http://192.168.1.50:8678`) to prevent cross-site hijacking. |

All configured in `.env`, loaded by systemd's `EnvironmentFile`.

## Security Notes

- The hub binds to `0.0.0.0` — it's accessible to any device on the LAN
- No authentication — this is a local-network-only device
- The `.env` file contains the BLE MAC address — treat it as semi-sensitive
- CORS is restricted by default to `localhost`. If you access the web UI via an IP address (e.g. `http://192.168.1.50:8678`), you MUST add `CORS_ORIGINS=http://192.168.1.50:8678` to your `.env` file. Do NOT set it to `*` or any website you visit can hijack the BedJet API.
- The MCP server connects to `localhost:8265` only — no external exposure
