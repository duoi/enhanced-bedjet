/**
 * Inline runtime editor. Displays hours/minutes select dropdowns and a
 * save button. Shown as an overlay card above the status strip in
 * ControlScreen.
 */
import { useState } from "react";

const HOURS = Array.from({ length: 13 }, (_, i) => i);
const MINUTES = Array.from({ length: 60 }, (_, i) => i);

export default function RuntimeEditor({ currentSeconds, onSave, onCancel }) {
  const initH = Math.floor((currentSeconds || 0) / 3600);
  const initM = Math.floor(((currentSeconds || 0) % 3600) / 60);
  const [hours, setHours] = useState(initH);
  const [minutes, setMinutes] = useState(initM);

  return (
    <div
      className="fade-up card"
      style={{ margin: "0 20px 16px", padding: "16px" }}
    >
      <div className="fan-header" style={{ marginBottom: "14px" }}>
        <div className="section-label" style={{ marginBottom: 0 }}>
          Set Runtime
        </div>
        <button
          onClick={onCancel}
          style={{
            background: "none",
            border: "none",
            color: "rgba(255,255,255,0.3)",
            fontSize: "16px",
            cursor: "pointer",
            padding: "0 4px",
          }}
        >
          ✕
        </button>
      </div>
      <div style={{ display: "flex", gap: "12px", alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <label htmlFor="runtime-hours" className="step-field-label">
            Hours
          </label>
          <select
            id="runtime-hours"
            aria-label="Hours"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="select-input"
            style={{ width: "100%" }}
          >
            {HOURS.map((h) => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label htmlFor="runtime-minutes" className="step-field-label">
            Minutes
          </label>
          <select
            id="runtime-minutes"
            aria-label="Minutes"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            className="select-input"
            style={{ width: "100%" }}
          >
            {MINUTES.map((m) => (
              <option key={m} value={m}>{String(m).padStart(2, "0")}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => onSave(hours, minutes)}
          className="primary-btn"
          style={{ flex: "none", width: "auto", padding: "10px 20px" }}
        >
          Set
        </button>
      </div>
    </div>
  );
}
