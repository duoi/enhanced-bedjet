/**
 * Hub API client. All device interaction flows through here — REST for
 * commands and CRUD, WebSocket for live state.
 */

const HUB_KEY = "bedjet_hub_address";

/** Empty string triggers proxy mode (relative URLs via Vite dev proxy). */
export const DEFAULT_HUB_ADDRESS = "";

/**
 * Returns `DEFAULT_HUB_ADDRESS` when no address has ever been stored,
 * `""` for proxy mode (relative URLs), or the explicit host:port string.
 */
export function getStoredHubAddress() {
  const stored = localStorage.getItem(HUB_KEY);
  if (stored === null) return DEFAULT_HUB_ADDRESS;
  return stored;
}

export function storeHubAddress(addr) {
  localStorage.setItem(HUB_KEY, addr);
}

/**
 * Resolve the hub base URL. Returns `""` for proxy mode (relative URLs),
 * or `http://<addr>` for direct connections. Throws only when no address
 * is missing (should not happen with a default hub address).
 */
function baseUrl(addr) {
  const a = addr !== undefined ? addr : getStoredHubAddress();
  if (a == null) throw new Error("Hub address not configured");
  if (!a) return "";
  return a.startsWith("http") ? a.replace(/\/$/, "") : `http://${a}`;
}

async function request(path, opts = {}) {
  const url = `${baseUrl()}/api${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || body?.error || `HTTP ${res.status}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function roundFan(pct) {
  return Math.max(5, Math.min(100, Math.round(pct / 5) * 5));
}

function roundTemp(c) {
  return Math.round(c * 2) / 2;
}

export const api = {
  // Device
  getDevice: () => request("/device"),
  setMode: (mode) =>
    request("/device/mode", {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  setFanSpeed: (percent) =>
    request("/device/fan", {
      method: "POST",
      body: JSON.stringify({ percent: roundFan(percent) }),
    }),
  setTemperature: (celsius) =>
    request("/device/temperature", {
      method: "POST",
      body: JSON.stringify({ celsius: roundTemp(celsius) }),
    }),
  setLed: (enabled) =>
    request("/device/led", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  setMute: (muted) =>
    request("/device/mute", {
      method: "POST",
      body: JSON.stringify({ muted }),
    }),
  syncClock: () => request("/device/clock/sync", { method: "POST" }),
  setRuntime: (hours, minutes) =>
    request("/device/runtime", {
      method: "POST",
      body: JSON.stringify({ hours, minutes }),
    }),
  activateMemory: (slot) =>
    request(`/device/memory/${slot}`, { method: "POST" }),
  activateDeviceBiorhythm: (slot) =>
    request(`/device/biorhythm/${slot}`, { method: "POST" }),

  // Programs
  getPrograms: () => request("/programs"),
  getProgram: (id) => request(`/programs/${id}`),
  createProgram: (data) =>
    request("/programs", { method: "POST", body: JSON.stringify(data) }),
  updateProgram: (id, data) =>
    request(`/programs/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProgram: (id) => request(`/programs/${id}`, { method: "DELETE" }),
  activateProgram: (id, startTime) =>
    request(`/programs/${id}/activate`, {
      method: "POST",
      body: JSON.stringify({ startTime }),
    }),
  stopProgram: () => request("/programs/stop", { method: "POST" }),
  getActiveProgram: () => request("/programs/active"),

  // Preferences
  getPreferences: () => request("/preferences"),
  updatePreferences: (prefs) =>
    request("/preferences", { method: "PUT", body: JSON.stringify(prefs) }),
};

/** One-shot connection test against an arbitrary hub address. */
export function testHubConnection(addr) {
  const url = baseUrl(addr);
  return fetch(`${url}/api/device`, { signal: AbortSignal.timeout(5000) }).then(
    (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },
  );
}

/** Open a WebSocket to the hub. Returns the socket instance. */
export function createWebSocket(addr, onMessage, onOpen, onClose) {
  let wsUrl;
  if (!addr) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    wsUrl = `${proto}://${location.host}/ws`;
  } else {
    const host = addr.replace(/^https?:\/\//, "").replace(/\/$/, "");
    const proto = addr.startsWith("https") ? "wss" : "ws";
    wsUrl = `${proto}://${host}/ws`;
  }
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch {
      /* ignore malformed frames */
    }
  };
  ws.onopen = () => onOpen?.();
  ws.onclose = () => onClose?.();
  ws.onerror = () => ws.close();
  return ws;
}
