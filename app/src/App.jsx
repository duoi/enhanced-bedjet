/**
 * Root app shell. Gates on hub address (shows SetupScreen when
 * unconfigured), provides tab navigation, and renders the persistent
 * bottom power bar.
 */
import { useState } from "react";
import { HubProvider, useHub } from "./hub";
import { api } from "./api";
import SetupScreen from "./SetupScreen";
import ControlScreen from "./ControlScreen";
import ProgramsScreen from "./ProgramsScreen";
import SettingsScreen from "./SettingsScreen";
import { getModeInfo, displayTemp, formatTemp } from "./utils";

function AppInner() {
  const { hubAddr, setHubAddr, bleConnected, deviceState, wsConnected, unit } =
    useHub();
  const [tab, setTab] = useState("control");

  const [skippedSetup, setSkippedSetup] = useState(false);

  if (hubAddr == null && !skippedSetup) {
    return (
      <SetupScreen
        onConnect={setHubAddr}
        onSkip={() => setSkippedSetup(true)}
      />
    );
  }

  const state = deviceState || {};
  const currentMode = state.mode || "standby";
  const modeInfo = getModeInfo(currentMode);
  const isOff = currentMode === "standby";

  return (
    <div className="app-shell">
      <div className="app-content">
        {/* ── Tab bar with status dot ────────────────── */}
        <div className="fade-up tab-row">
          {["control", "programs", "settings"].map((t) => (
            <button
              key={t}
              className={`tab-btn ${tab === t ? "active" : ""}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
          <div className="tab-status">
            {!wsConnected && (
              <span className="offline-label">offline</span>
            )}
            <div
              className={`status-dot ${bleConnected ? "pulse" : ""}`}
              style={{
                "--dot-color": bleConnected
                  ? "#4ade80"
                  : wsConnected
                    ? "#ffd93d"
                    : "#f87171",
              }}
            />
          </div>
        </div>

        {/* ── Screen ────────────────────────────────────── */}
        <div>
          {tab === "control" && <ControlScreen />}
          {tab === "programs" && <ProgramsScreen />}
          {tab === "settings" && <SettingsScreen />}
        </div>
      </div>

      {/* ── Bottom power bar ────────────────────────────── */}
      <div className="bottom-bar">
        <div className="bottom-bar-left">
          <div
            className="status-dot"
            style={{ "--dot-color": modeInfo.color }}
          />
          <span className="bottom-bar-mode">{modeInfo.label}</span>
          {!isOff && state.targetTemperatureC != null && (
            <>
              <span className="bottom-bar-sep">·</span>
              <span className="bottom-bar-stats">
                {formatTemp(
                  displayTemp(state.targetTemperatureC, unit),
                  unit,
                )}
                ° · {state.fanSpeedPercent || 0}%
              </span>
            </>
          )}
        </div>
        <button
          onClick={() =>
            api.setMode(isOff ? "cool" : "standby").catch(() => {})
          }
          className="power-btn"
          style={{
            background: isOff
              ? "rgba(255,255,255,0.06)"
              : "rgba(255,255,255,0.08)",
            borderColor: isOff
              ? "rgba(255,255,255,0.08)"
              : "rgba(255,255,255,0.15)",
            color: isOff ? "rgba(255,255,255,0.3)" : "white",
          }}
        >
          {isOff ? "Start" : "Stop"}
        </button>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <HubProvider>
      <AppInner />
    </HubProvider>
  );
}
