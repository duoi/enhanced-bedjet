/**
 * Main device control screen. Provides the temperature arc dial, mode
 * selector, fan speed slider, and live status readout. All values come
 * from the hub WebSocket; commands are debounced before sending.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import { useHub } from "./hub";
import { api } from "./api";
import {
  MODES,
  getModeInfo,
  displayTemp,
  toApiTemp,
  formatTemp,
  formatRuntime,
} from "./utils";
import TempArc from "./TempArc";
import RuntimeEditor from "./RuntimeEditor";

const FAN_PRESETS = [
  { label: "Whisper", value: 15 },
  { label: "Low", value: 30 },
  { label: "Med", value: 55 },
  { label: "High", value: 75 },
  { label: "Turbo", value: 100 },
];

export default function ControlScreen() {
  const { deviceState, activeProgram, unit, setPreferences } = useHub();
  const [localTemp, setLocalTemp] = useState(null);
  const [localFan, setLocalFan] = useState(null);
  const [editingRuntime, setEditingRuntime] = useState(false);
  const [pendingMode, setPendingMode] = useState(null);
  const tempTimer = useRef(null);
  const fanTimer = useRef(null);

  const state = deviceState || {};
  const serverMode = state.mode || "standby";
  const currentMode = pendingMode ?? serverMode;
  const modeInfo = getModeInfo(currentMode);

  const serverDisplay = displayTemp(state.targetTemperatureC ?? 22, unit);
  const minC = state.minTemperatureC || 19;
  const maxC = state.maxTemperatureC || 43;
  const minDisplay = displayTemp(minC, unit);
  const maxDisplay = displayTemp(maxC, unit);
  const rawSlider = localTemp ?? serverDisplay;
  const tempSlider = Math.max(minDisplay, Math.min(maxDisplay, rawSlider));
  const tempDisplay = Math.round(tempSlider);
  const tempC = localTemp != null ? toApiTemp(tempDisplay, unit) : (state.targetTemperatureC ?? 22);
  const fanPct = localFan ?? state.fanSpeedPercent ?? 0;

  useEffect(() => {
    if (localTemp !== null && Math.abs(serverDisplay - tempDisplay) < 1) {
      setLocalTemp(null);
    }
  }, [serverDisplay, localTemp, tempDisplay]);

  useEffect(() => {
    if (localFan !== null && Math.abs((state.fanSpeedPercent ?? 0) - localFan) < 3) {
      setLocalFan(null);
    }
  }, [state.fanSpeedPercent, localFan]);

  const tempColor = (() => {
    const range = maxC - minC;
    if (range <= 0) return "#c3e88d";
    const pct = (tempC - minC) / range;
    if (pct > 0.65) return "#ff6b35";
    if (pct < 0.35) return "#5bc8f5";
    return "#c3e88d";
  })();

  const onTempChange = useCallback(
    (displayVal) => {
      const clamped = Math.max(minDisplay, Math.min(maxDisplay, displayVal));
      setLocalTemp(clamped);
      clearTimeout(tempTimer.current);
      tempTimer.current = setTimeout(() => {
        api.setTemperature(toApiTemp(Math.round(clamped), unit)).catch(() => setLocalTemp(null));
      }, 300);
    },
    [unit, minDisplay, maxDisplay],
  );

  const onFanChange = useCallback((pct) => {
    const clamped = Math.max(5, Math.min(100, Math.round(pct / 5) * 5));
    setLocalFan(clamped);
    clearTimeout(fanTimer.current);
    fanTimer.current = setTimeout(() => {
      api.setFanSpeed(clamped).catch(() => setLocalFan(null));
    }, 300);
  }, []);

  useEffect(() => {
    if (pendingMode != null && serverMode === pendingMode) {
      setPendingMode(null);
    }
  }, [serverMode, pendingMode]);

  const onModeChange = (modeId) => {
    setPendingMode(modeId);
    setLocalTemp(null);
    setLocalFan(null);
    clearTimeout(tempTimer.current);
    clearTimeout(fanTimer.current);
    api.setMode(modeId).catch(() => setPendingMode(null));
  };

  const quickTemps =
    unit === "fahrenheit" ? [66, 70, 75, 82, 90] : [19, 22, 25, 30, 35];

  return (
    <div className="fade-up">
      {/* Active program banner */}
      {activeProgram && (
        <div
          className="active-banner"
          style={{ margin: "8px 20px 0", padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}
        >
          <div>
            <div
              className="active-banner-title"
              style={{ fontSize: "12px", marginBottom: "2px" }}
            >
              ▶ {activeProgram.programName}
            </div>
            <div className="active-banner-subtitle">
              Step {activeProgram.currentStepIndex + 1} of{" "}
              {activeProgram.totalSteps}
            </div>
          </div>
          <button
            onClick={() => api.stopProgram().catch(() => {})}
            className="danger-btn"
            style={{ padding: "6px 12px", fontSize: "11px" }}
          >
            Stop
          </button>
        </div>
      )}

      {/* Temperature arc */}
      <div className="fade-up temp-section">
        <div style={{ position: "relative" }}>
          <TempArc
            value={tempSlider}
            min={minDisplay}
            max={maxDisplay}
            mode={currentMode}
            onChange={onTempChange}
          />
          <div className="temp-center">
            <div
              className="temp-display"
              style={{
                color: tempColor,
                filter: `drop-shadow(0 0 20px ${tempColor}60)`,
              }}
            >
              {formatTemp(tempDisplay, unit)}
            </div>
            <button
              onClick={() => {
                const newUnit =
                  unit === "fahrenheit" ? "celsius" : "fahrenheit";
                api
                  .updatePreferences({ temperatureUnit: newUnit })
                  .then((updated) => setPreferences(updated))
                  .catch(() => {});
              }}
              className="temp-unit-toggle"
            >
              °{unit === "fahrenheit" ? "F" : "C"}
            </button>
          </div>
        </div>

        {/* Quick temp presets */}
        <div className="temp-presets">
          {quickTemps.map((t) => (
            <button
              key={t}
              onClick={() => onTempChange(t)}
              className={`temp-chip ${Math.round(tempDisplay) === t ? "active" : ""}`}
            >
              {t}°
            </button>
          ))}
        </div>
      </div>

      {/* Mode selector */}
      <div className="fade-up" style={{ padding: "0 20px 12px" }}>
        <div className="section-label">Mode</div>
        <div className="mode-grid">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={`mode-btn ${currentMode === m.id ? "active" : ""}${pendingMode === m.id ? " loading" : ""}`}
              onClick={() => onModeChange(m.id)}
              disabled={pendingMode != null}
              style={{
                borderColor:
                  currentMode === m.id ? `${m.color}60` : undefined,
                color: currentMode === m.id ? m.color : undefined,
              }}
            >
              <span style={{ fontSize: "16px" }}>{m.icon}</span>
              <span>{m.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Fan speed */}
      <div className="fade-up card" style={{ margin: "0 20px 12px" }}>
        <div className="fan-header">
          <div className="section-label" style={{ marginBottom: 0 }}>
            Fan Speed
          </div>
          <div className="fan-value">
            {Math.round(fanPct)}
            <span className="fan-value-unit">%</span>
          </div>
        </div>
        <div className="slider-wrap" style={{ position: "relative" }}>
          <div
            className="fan-fill"
            style={{ width: `${fanPct}%` }}
          />
          <input
            type="range"
            min={5}
            max={100}
            step={5}
            value={Math.max(5, fanPct)}
            onChange={(e) => onFanChange(Number(e.target.value))}
          />
        </div>
        <div className="fan-presets">
          {FAN_PRESETS.map(({ label, value }) => (
            <button
              key={label}
              onClick={() => onFanChange(value)}
              className="fan-preset"
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Runtime editor overlay */}
      {editingRuntime && (
        <RuntimeEditor
          currentSeconds={state.runtimeRemainingSeconds || 0}
          onSave={(hours, minutes) => {
            api.setRuntime(hours, minutes).catch(() => {});
            setEditingRuntime(false);
          }}
          onCancel={() => setEditingRuntime(false)}
        />
      )}

      {/* Status strip */}
      <div className="fade-up status-strip">
        <div
          role="button"
          tabIndex={0}
          className="card status-card"
          onClick={() => setEditingRuntime(true)}
          onKeyDown={(e) =>
            (e.key === "Enter" || e.key === " ") && setEditingRuntime(true)
          }
          style={{ cursor: "pointer" }}
        >
          <div className="section-label" style={{ marginBottom: "4px" }}>
            Runtime
          </div>
          <div className="status-card-value">
            {formatRuntime(state.runtimeRemainingSeconds)}
          </div>
        </div>
        {[
          {
            label: "Ambient",
            value: state.ambientTemperatureC
              ? `${formatTemp(displayTemp(state.ambientTemperatureC, unit), unit)}°`
              : "—",
            accent: true,
          },
          { label: "Mode", value: modeInfo.label },
        ].map((s) => (
          <div key={s.label} className="card status-card">
            <div className="section-label" style={{ marginBottom: "4px" }}>
              {s.label}
            </div>
            <div
              className="status-card-value"
              style={{ color: s.accent ? "#5bc8f5" : undefined }}
            >
              {s.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
