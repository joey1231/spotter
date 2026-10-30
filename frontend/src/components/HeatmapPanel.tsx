import { useEffect } from "react";
import type { HeatMetric } from "../lib/types";
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS } from "../lib/risk";
import { formatTime } from "../lib/format";

interface Props {
  departureTs: number;
  hour: number;
  onHour: (h: number) => void;
  metric: HeatMetric;
  onMetric: (m: HeatMetric) => void;
  visible: boolean;
  onVisible: (v: boolean) => void;
  playing: boolean;
  onPlaying: (p: boolean) => void;
  loading: boolean;
  error: string | null;
}

const MAX_HOUR = 48;
const METRICS: { key: HeatMetric; label: string }[] = [
  { key: "risk", label: "Overall" },
  { key: "wind", label: "Wind" },
  { key: "rain", label: "Rain" },
  { key: "snow", label: "Snow" },
];

export default function HeatmapPanel(props: Props) {
  const { departureTs, hour, onHour, metric, onMetric, visible, onVisible, playing, onPlaying, loading, error } = props;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => onHour((hour + 1) % (MAX_HOUR + 1)), 450);
    return () => window.clearInterval(timer);
  }, [playing, hour, onHour]);

  return (
    <div className="heat-panel">
      <div className="heat-top">
        <label className="check">
          <input type="checkbox" checked={visible} onChange={(e) => onVisible(e.target.checked)} />
          Weather heatmap
        </label>
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {METRICS.map((m) => (
            <button
              key={m.key}
              type="button"
              role="radio"
              aria-checked={metric === m.key}
              className={metric === m.key ? "on" : ""}
              onClick={() => onMetric(m.key)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <span className="heat-status">{loading ? "Loading forecast grid…" : error ?? ""}</span>
      </div>
      <div className="heat-slider">
        <button
          type="button"
          className="play"
          onClick={() => onPlaying(!playing)}
          aria-label={playing ? "Pause" : "Play"}
          title={playing ? "Pause" : "Play 0–48 h"}
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={MAX_HOUR}
          step={1}
          value={hour}
          onChange={(e) => {
            onPlaying(false);
            onHour(Number(e.target.value));
          }}
          aria-label="Forecast hour after departure"
        />
        <div className="heat-time">
          <b>+{hour}h</b>
          <span>{formatTime(departureTs + hour * 3600)}</span>
        </div>
      </div>
      <div className="legend">
        {RISK_LEVELS.map((l) => (
          <span key={l}>
            <i style={{ background: RISK_COLOR[l] }} />
            {RISK_LABEL[l]}
          </span>
        ))}
        <span className="muted">· lettered pins = truck position at this hour</span>
      </div>
    </div>
  );
}
