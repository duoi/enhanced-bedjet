/**
 * Circular temperature arc using react-circular-slider-svg for
 * reliable touch/mouse interaction. The arc spans 260° with a gap
 * on the right side. Visual styling is applied via CSS.
 */
import CircularSlider from "react-circular-slider-svg";

const MODE_COLORS = {
  cool: "#5bc8f5",
  heat: "#ff6b35",
  turbo: "#ffd93d",
  extended_heat: "#ff8c42",
  dry: "#c3e88d",
  standby: "#444c56",
};

export default function TempArc({ value, min, max, mode, onChange }) {
  const color = MODE_COLORS[mode] || "#c3e88d";
  // When the BedJet constrains min===max (e.g. Turbo mode locks temp),
  // widen the range downward so the arc renders as nearly full.
  const safeMin = min === max ? min - 2 : min;
  const safeMax = min === max ? max + 0.1 : max;
  const safeValue = Math.max(safeMin + 0.01, Math.min(safeMax - 0.01, value));

  return (
    <div
      className="temp-arc-wrap"
      style={{
        width: 190,
        height: 190,
        position: "relative",
        "--arc-color": color,
      }}
    >
      <CircularSlider
        size={190}
        trackWidth={9}
        minValue={safeMin}
        maxValue={safeMax}
        startAngle={50}
        endAngle={310}
        angleType={{ direction: "cw", axis: "-y" }}
        disabled={min === max}
        handle1={{
          value: safeValue,
          onChange: (v) => onChange?.(v),
        }}
        arcColor={color}
        arcBackgroundColor="rgba(255,255,255,0.06)"
      />
    </div>
  );
}
