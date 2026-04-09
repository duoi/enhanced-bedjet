/** Temperature conversion and shared constants for the BedJet app. */

export function cToF(c) {
  return Math.round(c * 9 / 5 + 32);
}

export function fToC(f) {
  return (f - 32) * 5 / 9;
}

/** Convert API celsius value to the user's display unit. */
export function displayTemp(celsius, unit) {
  if (unit === "fahrenheit") return cToF(celsius);
  return Math.round(celsius * 2) / 2;
}

/** Convert a display-unit value back to celsius for the API. */
export function toApiTemp(displayValue, unit) {
  const c = unit === "fahrenheit" ? fToC(displayValue) : displayValue;
  return Math.round(c * 2) / 2;
}

/** Format a temperature value as a display string (no unit symbol). */
export function formatTemp(value, unit) {
  if (unit === "fahrenheit") return `${Math.round(value)}`;
  return (Math.round(value * 2) / 2).toFixed(1);
}

export function formatRuntime(seconds) {
  if (!seconds || seconds <= 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export const MODES = [
  { id: "heat", label: "Heat", icon: "🔥", color: "#ff6b35" },
  { id: "cool", label: "Cool", icon: "❄️", color: "#5bc8f5" },
  { id: "dry", label: "Dry", icon: "💨", color: "#c3e88d" },
  { id: "turbo", label: "Turbo", icon: "⚡", color: "#ffd93d" },
  { id: "extended_heat", label: "Ext Heat", icon: "🔥", color: "#ff8c42" },
];

const STANDBY_MODE = { id: "standby", label: "Off", icon: "◌", color: "#444c56" };

export function getModeInfo(modeId) {
  return MODES.find((m) => m.id === modeId) || STANDBY_MODE;
}
