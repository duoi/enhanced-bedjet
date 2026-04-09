#!/usr/bin/env python3
"""MCP server for BedJet Hub — exposes device, preference, and program
controls as MCP tools over stdio (JSON-RPC 2.0)."""

import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass

HUB_URL = "http://localhost:8265"


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

@dataclass
class RpcError(Exception):
    code: int
    message: str
    data: object = None


def rpc_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def rpc_error(id_, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


# ---------------------------------------------------------------------------
# Hub REST helpers
# ---------------------------------------------------------------------------

def hub_get(path):
    url = f"{HUB_URL}/api{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RpcError(-32000, f"Hub unreachable: {e}")


def hub_post(path, body=None):
    url = f"{HUB_URL}/api{path}"
    data = json.dumps(body).encode() if body else b""
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            raise RpcError(-32000, f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RpcError(-32000, f"Hub unreachable: {e}")


def hub_put(path, body):
    url = f"{HUB_URL}/api{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RpcError(-32000, f"Hub unreachable: {e}")


def hub_delete(path):
    url = f"{HUB_URL}/api{path}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        raise RpcError(-32000, f"Hub unreachable: {e}")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "get_device_status",
        "description": "Get the current BedJet device status including connection state, temperature, mode, and metadata.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_device_mode",
        "description": "Set the BedJet operating mode.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["standby", "heat", "turbo", "extended_heat", "cool", "dry"],
                    "description": "The operating mode to set.",
                }
            },
            "required": ["mode"],
        },
    },
    {
        "name": "set_fan_speed",
        "description": "Set the BedJet fan speed percentage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "percent": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 100,
                    "description": "Fan speed percentage (5-100).",
                }
            },
            "required": ["percent"],
        },
    },
    {
        "name": "set_target_temperature",
        "description": "Set the BedJet target temperature in Celsius.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "celsius": {
                    "type": "number",
                    "description": "Target temperature in Celsius (10.0 - 40.0).",
                }
            },
            "required": ["celsius"],
        },
    },
    {
        "name": "set_led",
        "description": "Enable or disable the BedJet LED.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "True to enable LED, false to disable.",
                }
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "set_mute",
        "description": "Mute or unmute the BedJet beeps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "muted": {
                    "type": "boolean",
                    "description": "True to mute beeps, false to unmute.",
                }
            },
            "required": ["muted"],
        },
    },
    {
        "name": "sync_clock",
        "description": "Sync the BedJet's internal clock to the system time.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_runtime",
        "description": "Set the BedJet run timer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Hours component of the runtime.",
                },
                "minutes": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Minutes component of the runtime.",
                },
            },
            "required": ["hours", "minutes"],
        },
    },
    {
        "name": "activate_memory",
        "description": "Activate a saved memory preset (slot 1, 2, or 3).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slot": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "description": "Memory slot to activate.",
                }
            },
            "required": ["slot"],
        },
    },
    {
        "name": "activate_biorhythm",
        "description": "Activate a saved biorhythm preset (slot 1, 2, or 3).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slot": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                    "description": "Biorhythm slot to activate.",
                }
            },
            "required": ["slot"],
        },
    },
    {
        "name": "get_preferences",
        "description": "Get current user preferences (temperature unit, default fan speed, auto clock sync).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_preferences",
        "description": "Update user preferences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "temperatureUnit": {
                    "type": "string",
                    "enum": ["F", "C"],
                    "description": "Temperature display unit.",
                },
                "defaultFanSpeedPercent": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 100,
                    "description": "Default fan speed percentage.",
                },
                "autoSyncClock": {
                    "type": "boolean",
                    "description": "Auto-sync clock on connect.",
                },
            },
        },
    },
    {
        "name": "list_programs",
        "description": "List all saved biorhythm programs.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_program",
        "description": "Create a new biorhythm program with steps and optional schedule.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Program name.",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": ["standby", "heat", "turbo", "extended_heat", "cool", "dry"],
                            },
                            "temperatureC": {"type": "number"},
                            "fanSpeedPercent": {"type": "integer"},
                            "durationMinutes": {"type": "integer", "minimum": 0},
                        },
                        "required": ["mode", "durationMinutes"],
                    },
                    "description": "Ordered list of program steps.",
                },
                "startTime": {
                    "type": "string",
                    "description": "Time of day to start the program (HH:MM format). Example: '22:30'. Requires 'days' to also be set."
                },
                "days": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    "description": "Days of the week to run the program (0=Monday, 6=Sunday). Requires 'startTime' to also be set."
                }
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_program",
        "description": "Get details of a specific biorhythm program.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "programId": {
                    "type": "string",
                    "description": "The program ID.",
                }
            },
            "required": ["programId"],
        },
    },
    {
        "name": "update_program",
        "description": "Update an existing biorhythm program.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "programId": {
                    "type": "string",
                    "description": "The program ID to update.",
                },
                "name": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string"},
                            "temperatureC": {"type": "number"},
                            "fanSpeedPercent": {"type": "integer"},
                            "durationMinutes": {"type": "integer"},
                        },
                        "required": ["mode", "durationMinutes"],
                    },
                },
                "startTime": {"type": "string", "description": "Time of day to start (HH:MM) or null to clear schedule."},
                "days": {"type": "array", "items": {"type": "integer"}, "description": "Days to run (0=Monday) or null to clear."}
            },
            "required": ["programId"],
        },
    },
    {
        "name": "delete_program",
        "description": "Delete a biorhythm program.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "programId": {
                    "type": "string",
                    "description": "The program ID to delete.",
                }
            },
            "required": ["programId"],
        },
    },
    {
        "name": "activate_program",
        "description": "Activate a biorhythm program to start running at a given time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "programId": {
                    "type": "string",
                    "description": "The program ID to activate.",
                },
                "startTime": {
                    "type": "string",
                    "description": "ISO 8601 timestamp for when the program should start.",
                },
            },
            "required": ["programId", "startTime"],
        },
    },
    {
        "name": "get_active_program",
        "description": "Get the currently active biorhythm program, if any.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "stop_program",
        "description": "Stop the currently active biorhythm program.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def call_tool(name, arguments):
    if name == "get_device_status":
        return hub_get("/device")

    elif name == "set_device_mode":
        return hub_post("/device/mode", {"mode": arguments["mode"]})

    elif name == "set_fan_speed":
        return hub_post("/device/fan", {"percent": arguments["percent"]})

    elif name == "set_target_temperature":
        return hub_post("/device/temperature", {"celsius": arguments["celsius"]})

    elif name == "set_led":
        return hub_post("/device/led", {"enabled": arguments["enabled"]})

    elif name == "set_mute":
        return hub_post("/device/mute", {"muted": arguments["muted"]})

    elif name == "sync_clock":
        return hub_post("/device/clock/sync")

    elif name == "set_runtime":
        return hub_post("/device/runtime", {
            "hours": arguments["hours"],
            "minutes": arguments["minutes"],
        })

    elif name == "activate_memory":
        return hub_post(f"/device/memory/{arguments['slot']}")

    elif name == "activate_biorhythm":
        return hub_post(f"/device/biorhythm/{arguments['slot']}")

    elif name == "get_preferences":
        return hub_get("/preferences")

    elif name == "update_preferences":
        body = {}
        if "temperatureUnit" in arguments:
            body["temperatureUnit"] = arguments["temperatureUnit"]
        if "defaultFanSpeedPercent" in arguments:
            body["defaultFanSpeedPercent"] = arguments["defaultFanSpeedPercent"]
        if "autoSyncClock" in arguments:
            body["autoSyncClock"] = arguments["autoSyncClock"]
        return hub_put("/preferences", body)

    elif name == "list_programs":
        return hub_get("/programs")

    elif name == "create_program":
        body = {"name": arguments["name"], "steps": arguments.get("steps", [])}
        if "startTime" in arguments:
            body["startTime"] = arguments["startTime"]
        if "days" in arguments:
            body["days"] = arguments["days"]
        return hub_post("/programs", body)

    elif name == "get_program":
        return hub_get(f"/programs/{arguments['programId']}")

    elif name == "update_program":
        body = {}
        if "name" in arguments:
            body["name"] = arguments["name"]
        if "steps" in arguments:
            body["steps"] = arguments["steps"]
        if "startTime" in arguments:
            body["startTime"] = arguments["startTime"]
        if "days" in arguments:
            body["days"] = arguments["days"]
        return hub_put(f"/programs/{arguments['programId']}", body)

    elif name == "delete_program":
        return hub_delete(f"/programs/{arguments['programId']}")

    elif name == "activate_program":
        return hub_post(f"/programs/{arguments['programId']}/activate", {
            "startTime": arguments["startTime"],
        })

    elif name == "get_active_program":
        return hub_get("/programs/active")

    elif name == "stop_program":
        return hub_post("/programs/stop")

    else:
        raise RpcError(-32601, f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def handle_message(msg):
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return rpc_result(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "bedjet", "version": "1.0.0"},
        })

    elif method == "notifications/initialized":
        return None  # notification, no response

    elif method == "tools/list":
        return rpc_result(id_, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            result = call_tool(tool_name, arguments)
            text = json.dumps(result, indent=2)
            return rpc_result(id_, {"content": [{"type": "text", "text": text}]})
        except RpcError as e:
            return rpc_result(id_, {
                "content": [{"type": "text", "text": f"Error: {e.message}"}],
                "isError": True,
            })
        except Exception as e:
            return rpc_result(id_, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })

    else:
        if id_ is not None:
            return rpc_error(id_, -32601, f"Method not found: {method}")
        return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_message(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
