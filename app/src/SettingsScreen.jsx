/**
 * Settings screen. Device info, LED / mute / clock controls,
 * temperature unit preference, memory presets, and hub connection
 * management.
 */
import { useState } from "react";
import { useHub } from "./hub";
import { api } from "./api";

export default function SettingsScreen() {
  const {
    bleConnected,
    wsConnected,
    deviceState,
    metadata,
    preferences,
    setPreferences,
    hubAddr,
    setHubAddr,
    unit,
  } = useHub();

  const [editingAddr, setEditingAddr] = useState(false);
  const [addrInput, setAddrInput] = useState(hubAddr);

  const state = deviceState || {};
  const meta = metadata || {};

  const autoSync = preferences?.autoSyncClock !== false;

  const toggleUnit = async () => {
    const newUnit = unit === "fahrenheit" ? "celsius" : "fahrenheit";
    try {
      const updated = await api.updatePreferences({
        temperatureUnit: newUnit,
      });
      setPreferences(updated);
    } catch {
      /* offline — ignore */
    }
  };

  const toggleAutoSync = async () => {
    try {
      const updated = await api.updatePreferences({
        autoSyncClock: !autoSync,
      });
      setPreferences(updated);
    } catch {
      /* offline — ignore */
    }
  };

  return (
    <div className="page-shell">
      {/* ── Connection ────────────────────────────────────── */}
      <div className="section-label">Connection</div>
      <div className="card" style={{ marginBottom: "20px", padding: "16px" }}>
        <StatusRow
          label="Hub"
          ok={wsConnected}
          text={wsConnected ? "Connected" : "Disconnected"}
        />
        <StatusRow
          label="BLE Device"
          ok={bleConnected}
          text={bleConnected ? "Connected" : "Disconnected"}
        />

        {editingAddr ? (
          <div
            style={{
              display: "flex",
              gap: "8px",
              marginTop: "8px",
            }}
          >
            <input
              value={addrInput}
              onChange={(e) => setAddrInput(e.target.value)}
              placeholder="192.168.1.x:8265"
              className="hub-input"
            />
            <button
              onClick={() => {
                setHubAddr(addrInput);
                setEditingAddr(false);
              }}
              className="icon-btn"
              style={{ color: "#4ade80" }}
            >
              ✓
            </button>
            <button
              onClick={() => {
                setAddrInput(hubAddr);
                setEditingAddr(false);
              }}
              className="icon-btn"
            >
              ✕
            </button>
          </div>
        ) : (
          <div className="settings-row" style={{ marginTop: "8px" }}>
            <span className="hub-addr-display">
              {hubAddr || "Not set"}
            </span>
            <button onClick={() => setEditingAddr(true)} className="icon-btn">
              Edit
            </button>
          </div>
        )}
      </div>

      {/* ── Device info ───────────────────────────────────── */}
      {meta.name && (
        <>
          <div className="section-label">Device</div>
          <div
            className="card"
            style={{ marginBottom: "20px", padding: "16px" }}
          >
            {[
              { label: "Name", value: meta.name },
              { label: "Model", value: meta.model?.toUpperCase() },
              { label: "Firmware", value: meta.firmwareVersion || "—" },
              { label: "Address", value: meta.address || "—" },
            ].map(({ label, value }) => (
              <div key={label} className="device-info-row">
                <span className="settings-label">{label}</span>
                <span className="device-info-value">{value}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Device controls ───────────────────────────────── */}
      <div className="section-label">Device Controls</div>
      <div className="card" style={{ marginBottom: "20px", padding: "16px" }}>
        <ToggleRow
          label="LED Ring"
          value={state.ledEnabled !== false}
          onChange={() =>
            api.setLed(state.ledEnabled === false).catch(() => {})
          }
        />
        <ToggleRow
          label="Mute Beeps"
          value={state.beepsMuted === true}
          onChange={() =>
            api.setMute(state.beepsMuted !== true).catch(() => {})
          }
        />
        <div className="settings-row">
          <span className="settings-label">Sync Clock</span>
          <button
            onClick={() => api.syncClock().catch(() => {})}
            className="icon-btn"
          >
            Sync
          </button>
        </div>
      </div>

      {/* ── Preferences ───────────────────────────────────── */}
      <div className="section-label">Preferences</div>
      <div className="card" style={{ marginBottom: "20px", padding: "16px" }}>
        <div className="settings-row">
          <span className="settings-label">Temperature Unit</span>
          <button onClick={toggleUnit} className="unit-btn">
            °{unit === "fahrenheit" ? "F" : "C"}
          </button>
        </div>
        <ToggleRow
          label="Auto Sync Clock"
          value={autoSync}
          onChange={toggleAutoSync}
        />
      </div>

      {/* ── Memory presets ────────────────────────────────── */}
      {meta.memoryNames && meta.memoryNames.some((n) => n) && (
        <>
          <div className="section-label">Memory Presets</div>
          <div className="preset-grid" style={{ marginBottom: "20px" }}>
            {meta.memoryNames.map((slotName, i) => (
              <button
                key={i}
                onClick={() => api.activateMemory(i + 1).catch(() => {})}
                disabled={!slotName}
                className="card"
                style={{
                  flex: 1,
                  padding: "14px 8px",
                  textAlign: "center",
                  cursor: slotName ? "pointer" : "default",
                  opacity: slotName ? 1 : 0.3,
                }}
              >
                <div className="preset-label">M{i + 1}</div>
                <div className="preset-value">{slotName || "—"}</div>
              </button>
            ))}
          </div>
        </>
      )}

      {/* ── Biorhythm presets ─────────────────────────────── */}
      {meta.biorhythmNames && meta.biorhythmNames.some((n) => n) && (
        <>
          <div className="section-label">Device Biorhythm Presets</div>
          <div className="preset-grid">
            {meta.biorhythmNames.map((slotName, i) => (
              <button
                key={i}
                onClick={() =>
                  api.activateDeviceBiorhythm(i + 1).catch(() => {})
                }
                disabled={!slotName}
                className="card"
                style={{
                  flex: 1,
                  padding: "14px 8px",
                  textAlign: "center",
                  cursor: slotName ? "pointer" : "default",
                  opacity: slotName ? 1 : 0.3,
                }}
              >
                <div className="preset-label">B{i + 1}</div>
                <div className="preset-value">{slotName || "—"}</div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Shared row components ───────────────────────────────── */

function StatusRow({ label, ok, text }) {
  return (
    <div className="status-row">
      <span className="settings-label">{label}</span>
      <div className="status-row-right">
        <div
          className="status-row-dot"
          style={{ background: ok ? "#4ade80" : "#f87171" }}
        />
        <span
          style={{
            color: ok ? "#4ade80" : "#f87171",
            fontSize: "12px",
          }}
        >
          {text}
        </span>
      </div>
    </div>
  );
}

function ToggleRow({ label, value, onChange }) {
  return (
    <div className="settings-row">
      <span className="settings-label">{label}</span>
      <button
        onClick={onChange}
        className="toggle-track"
        style={{ background: value ? "#4ade80" : "rgba(255,255,255,0.1)" }}
      >
        <div
          className="toggle-thumb"
          style={{ left: value ? "21px" : "3px" }}
        />
      </button>
    </div>
  );
}
