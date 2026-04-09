/**
 * Program management screen. Lists saved biorhythm programs, supports
 * creation / editing / deletion / activation, and shows the currently
 * active program's progress.
 */
import { useState, useEffect, useCallback } from "react";
import { useHub } from "./hub";
import { api } from "./api";
import { displayTemp, toApiTemp } from "./utils";
import {
  computeStepTimes,
  endTimesToDurations,
  minutesToTime,
  timeToMinutes,
  computeDurationMinutes,
  validateStepTimes,
} from "./timeUtils";

/* 24h ↔ 12h helpers */
function to12h(time24) {
  const [h, m] = time24.split(":").map(Number);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 || 12;
  return { h: h12, m, ampm };
}

function to24h(h12, m, ampm) {
  let h = h12 % 12;
  if (ampm === "PM") h += 12;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function format12h(time24) {
  const { h, m, ampm } = to12h(time24);
  return `${h}:${String(m).padStart(2, "0")} ${ampm}`;
}

const HOURS_12 = Array.from({ length: 12 }, (_, i) => i + 1);
const MINUTES_60 = Array.from({ length: 60 }, (_, i) => i);
const DURATION_OPTIONS = Array.from({ length: 144 }, (_, i) => (i + 1) * 10);
const FAN_OPTIONS = Array.from({ length: 20 }, (_, i) => (i + 1) * 5);

export default function ProgramsScreen() {
  const { activeProgram, unit } = useHub();
  const [programs, setPrograms] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setPrograms(await api.getPrograms());
    } catch {
      /* offline — keep stale list */
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (editing) {
    return (
      <ProgramEditor
        program={editing}
        unit={unit}
        onSave={async (data) => {
          if (editing.id) {
            await api.updateProgram(editing.id, data);
          } else {
            await api.createProgram(data);
          }
          setEditing(null);
          load();
        }}
        onDelete={
          editing.id
            ? async () => {
                await api.deleteProgram(editing.id);
                setEditing(null);
                load();
              }
            : null
        }
        onActivate={
          editing.id
            ? async () => {
                await api.activateProgram(
                  editing.id,
                  new Date().toISOString(),
                );
                setEditing(null);
                load();
              }
            : null
        }
        onBack={() => setEditing(null)}
      />
    );
  }

  return (
    <div className="page-shell">
      {/* Active program banner */}
      {activeProgram && <ActiveBanner program={activeProgram} onStop={() => api.stopProgram().then(load).catch(() => {})} />}

      <div className="section-label">Programs</div>

      {loading ? (
        <div className="loading-state">Loading…</div>
      ) : programs.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="program-list">
          {programs.map((p) => (
            <ProgramCard
              key={p.id}
              program={p}
              onEdit={() => setEditing(p)}
              onPlay={() =>
                api
                  .activateProgram(p.id, new Date().toISOString())
                  .then(load)
                  .catch(() => {})
              }
            />
          ))}
        </div>
      )}

      <button
        onClick={() => setEditing({ name: "", steps: [] })}
        className="primary-btn"
      >
        + Create Program
      </button>
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────── */

function ActiveBanner({ program, onStop }) {
  const pct =
    program.totalSteps > 0
      ? ((program.currentStepIndex + 1) / program.totalSteps) * 100
      : 0;

  return (
    <div className="active-banner" style={{ marginBottom: "20px" }}>
      <div className="active-banner-header">
        <div>
          <div className="active-banner-title">▶ {program.programName}</div>
          <div className="active-banner-subtitle">
            Step {program.currentStepIndex + 1} of {program.totalSteps}
          </div>
        </div>
        <button onClick={onStop} className="danger-btn">
          Stop
        </button>
      </div>
      <div className="active-banner-progress">
        <div className="active-banner-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">🌙</div>
      <div className="empty-state-text">No programs yet</div>
      <div className="empty-state-sub">
        Create a biorhythm program for automated sleep climate
      </div>
    </div>
  );
}

function ProgramCard({ program, onEdit, onPlay }) {
  const steps = program.steps || [];
  const totalMin = steps.reduce(
    (sum, s) => sum + (s.durationMinutes || 0),
    0,
  );
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;

  return (
    <div className="program-card">
      <div onClick={onEdit} className="program-card-body">
        <div className="program-card-name">{program.name}</div>
        <div className="program-card-meta">
          <span>
            {steps.length} steps · {hours > 0 ? `${hours}h ` : ""}
            {mins}m
          </span>
        </div>
      </div>
      <button onClick={onPlay} className="program-card-play">
        ▶
      </button>
    </div>
  );
}

/* ── Program editor ──────────────────────────────────────── */

const DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

function ProgramEditor({ program, unit, onSave, onDelete, onActivate, onBack }) {
  const [name, setName] = useState(program.name || "");
  const [scheduled, setScheduled] = useState(!!program.startTime);
  const [startTime, setStartTime] = useState(program.startTime || "22:00");
  const [days, setDays] = useState(program.days || []);
  const [steps, setSteps] = useState(
    (program.steps || []).map((s) => ({ ...s })),
  );
  const [saving, setSaving] = useState(false);

  const toggleDay = (dayIndex) => {
    setDays((prev) =>
      prev.includes(dayIndex)
        ? prev.filter((d) => d !== dayIndex)
        : [...prev, dayIndex].sort(),
    );
  };

  const timedSteps = scheduled
    ? computeStepTimes(startTime, steps)
    : steps.map((s) => ({ ...s, startTime: null, endTime: null }));

  const addStep = () => {
    setSteps([
      ...steps,
      {
        temperatureC: 22,
        fanSpeedPercent: 50,
        durationMinutes: 30,
        timingType: "duration",
      },
    ]);
  };

  const updateStepEndTime = (idx, endTime) => {
    setSteps((prev) => {
      const next = prev.map((s, i) => ({ ...s }));
      const stepStart =
        idx === 0
          ? timeToMinutes(startTime)
          : timeToMinutes(computeStepTimes(startTime, next.slice(0, idx))[idx - 1].endTime);
      const dur = computeDurationMinutes(stepStart, timeToMinutes(endTime));
      next[idx] = { ...next[idx], durationMinutes: dur, _endTime: endTime };
      return next;
    });
  };

  const updateStepDuration = (idx, mins) => {
    setSteps((prev) => {
      const next = prev.map((s) => ({ ...s }));
      const stepStart =
        idx === 0
          ? timeToMinutes(startTime)
          : timeToMinutes(
              computeStepTimes(startTime, next.slice(0, idx))[idx - 1].endTime,
            );
      const endMin = (stepStart + mins) % 1440;
      next[idx] = {
        ...next[idx],
        durationMinutes: mins,
        _endTime: minutesToTime(endMin),
      };
      return next;
    });
  };

  const updateStep = (idx, field, value) => {
    setSteps((prev) =>
      prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s)),
    );
  };

  const removeStep = (idx) => {
    setSteps((prev) => prev.filter((_, i) => i !== idx));
  };

  const moveStep = (idx, dir) => {
    setSteps((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const errors = scheduled ? validateStepTimes(startTime, steps) : [];

  const handleSave = async () => {
    if (!name.trim() || errors.length > 0) return;
    setSaving(true);
    try {
      const apiSteps = steps.map(({ _endTime, startTime: _s, endTime: _e, ...rest }) => rest);
      const data = { name: name.trim(), steps: apiSteps };
      if (scheduled) {
        data.startTime = startTime;
        data.days = days;
      } else {
        data.startTime = null;
        data.days = [];
      }
      await onSave(data);
    } catch {
      /* handled by caller */
    }
    setSaving(false);
  };

  return (
    <div className="page-shell">
      <button onClick={onBack} className="back-btn">
        ← Back
      </button>

      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Program name"
        className="program-name-input"
      />

      <div style={{ marginBottom: "20px" }}>
        <button
          onClick={() => setScheduled((s) => !s)}
          className={`schedule-toggle ${scheduled ? "active" : ""}`}
        >
          🕐 Schedule
        </button>
        {scheduled && (
          <div className="schedule-panel">
            <div>
              <div className="section-label">Start Time</div>
              <TimeSelect
                value={startTime}
                onChange={setStartTime}
                idPrefix="program-start"
              />
            </div>
            <div>
              <div className="section-label">Days</div>
              <div style={{ display: "flex", gap: "4px" }}>
                {DAY_LABELS.map((label, i) => (
                  <button
                    key={i}
                    aria-pressed={days.includes(i)}
                    onClick={() => toggleDay(i)}
                    className="day-btn"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="section-label">Steps</div>

      <div className="program-list">
        {timedSteps.map((step, i) => (
          <StepCard
            key={i}
            index={i}
            step={step}
            unit={unit}
            total={timedSteps.length}
            onChange={(field, val) => updateStep(i, field, val)}
            onEndTimeChange={(endTime) => updateStepEndTime(i, endTime)}
            onDurationChange={(mins) => updateStepDuration(i, mins)}
            onMove={(dir) => moveStep(i, dir)}
            onRemove={() => removeStep(i)}
          />
        ))}
      </div>

      {errors.length > 0 && (
        <div className="error-box">
          {errors.map((e, i) => (
            <div key={i}>{e}</div>
          ))}
        </div>
      )}

      <button
        onClick={addStep}
        className="secondary-btn"
        style={{ marginBottom: "16px" }}
      >
        + Add Step
      </button>

      <div className="btn-row">
        <button
          onClick={handleSave}
          disabled={saving || !name.trim() || errors.length > 0}
          className="primary-btn"
          style={{ flex: 1 }}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {onActivate && (
          <button
            onClick={onActivate}
            className="primary-btn"
            style={{ flex: 1 }}
          >
            ▶ Activate
          </button>
        )}
      </div>

      {onDelete && (
        <button onClick={onDelete} className="danger-btn-full">
          Delete Program
        </button>
      )}
    </div>
  );
}

function StepCard({
  index,
  step,
  unit,
  total,
  onChange,
  onEndTimeChange,
  onDurationChange,
  onMove,
  onRemove,
}) {
  const isUntil = step.timingType === "until";
  const tempDisplay =
    step.temperatureC != null
      ? Math.round(displayTemp(step.temperatureC, unit))
      : "";

  const minTemp = unit === "fahrenheit" ? 66 : 19;
  const maxTemp = unit === "fahrenheit" ? 104 : 40;
  const tempOptions = Array.from(
    { length: maxTemp - minTemp + 1 },
    (_, i) => minTemp + i,
  );

  const durationH = Math.floor((step.durationMinutes || 0) / 60);
  const durationM = (step.durationMinutes || 0) % 60;
  const durationLabel =
    durationH > 0 ? `${durationH}h ${durationM}m` : `${durationM}m`;

  return (
    <div className="card" style={{ padding: "14px" }}>
      <div className="step-header">
        <div className="step-header-left">
          <span className="step-index">{index + 1}</span>
          {step.startTime && (
            <span className="step-time">{format12h(step.startTime)} →</span>
          )}
          <span className="step-duration-summary">{durationLabel}</span>
        </div>
        <div className="step-actions">
          <button
            onClick={() => onMove(-1)}
            className="icon-btn"
            disabled={index === 0}
          >
            ↑
          </button>
          <button
            onClick={() => onMove(1)}
            className="icon-btn"
            disabled={index === total - 1}
          >
            ↓
          </button>
          <button
            onClick={onRemove}
            className="icon-btn"
            style={{ color: "#f87171" }}
          >
            ×
          </button>
        </div>
      </div>

      <div className="step-field-grid">
        <div>
          <label className="step-field-label" htmlFor={`step-temp-${index}`}>
            TEMP °{unit === "fahrenheit" ? "F" : "C"}
          </label>
          <select
            id={`step-temp-${index}`}
            value={tempDisplay}
            onChange={(e) =>
              onChange("temperatureC", toApiTemp(Number(e.target.value), unit))
            }
            className="select-input"
            style={{ width: "100%" }}
          >
            {tempOptions.map((t) => (
              <option key={t} value={t}>{t}°</option>
            ))}
          </select>
        </div>
        <div>
          <label className="step-field-label" htmlFor={`step-fan-${index}`}>
            FAN %
          </label>
          <select
            id={`step-fan-${index}`}
            value={step.fanSpeedPercent ?? 50}
            onChange={(e) => onChange("fanSpeedPercent", Number(e.target.value))}
            className="select-input"
            style={{ width: "100%" }}
          >
            {FAN_OPTIONS.map((f) => (
              <option key={f} value={f}>{f}%</option>
            ))}
          </select>
        </div>
      </div>

      <div className="timing-bar">
        <button
          className={`timing-segment timing-segment-left ${!isUntil ? "active" : ""}`}
          onClick={() => onChange("timingType", "duration")}
        >
          for
        </button>
        <div className="timing-divider" />
        <button
          className={`timing-segment timing-segment-right ${isUntil ? "active" : ""}`}
          onClick={() => onChange("timingType", "until")}
        >
          until
        </button>
        <div className="timing-divider" />
        {isUntil ? (
          <div className="timing-value" style={{ padding: "0 6px", gap: "4px" }}>
            <TimeSelect
              value={step.endTime || "00:00"}
              onChange={onEndTimeChange}
              idPrefix={`step-end-${index}`}
              labelPrefix="End"
              compact
            />
          </div>
        ) : (
          <div className="timing-value" style={{ padding: "0 8px" }}>
            <select
              aria-label="Duration (mins)"
              value={step.durationMinutes || 30}
              onChange={(e) => onDurationChange(Number(e.target.value))}
              className="select-input select-input-compact"
            >
              {DURATION_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d >= 60 ? `${Math.floor(d / 60)}h ${d % 60 ? `${d % 60}m` : ""}` : `${d}m`}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Reusable 12-hour time select: hour (1-12), minute (0-59), AM/PM.
 * `value` and `onChange` work with 24h "HH:MM" strings for internal consistency.
 */
function TimeSelect({ value, onChange, idPrefix, labelPrefix = "", compact }) {
  const { h, m, ampm } = to12h(value);
  const cls = compact ? "select-input select-input-compact" : "select-input";
  const hourLabel = labelPrefix ? `${labelPrefix} Hour` : "Hour";
  const minLabel = labelPrefix ? `${labelPrefix} Minute` : "Minute";
  const ampmLabel = labelPrefix ? `${labelPrefix} AM/PM` : "AM/PM";

  const set = (newH, newM, newAmpm) => onChange(to24h(newH, newM, newAmpm));

  return (
    <div className="time-select-group">
      <select
        id={`${idPrefix}-hour`}
        aria-label={hourLabel}
        value={h}
        onChange={(e) => set(Number(e.target.value), m, ampm)}
        className={cls}
      >
        {HOURS_12.map((hr) => (
          <option key={hr} value={hr}>{hr}</option>
        ))}
      </select>
      <span className="time-select-sep">:</span>
      <select
        id={`${idPrefix}-min`}
        aria-label={minLabel}
        value={m}
        onChange={(e) => set(h, Number(e.target.value), ampm)}
        className={cls}
      >
        {MINUTES_60.map((mn) => (
          <option key={mn} value={mn}>{String(mn).padStart(2, "0")}</option>
        ))}
      </select>
      <select
        id={`${idPrefix}-ampm`}
        aria-label={ampmLabel}
        value={ampm}
        onChange={(e) => set(h, m, e.target.value)}
        className={cls}
      >
        <option value="AM">AM</option>
        <option value="PM">PM</option>
      </select>
    </div>
  );
}
