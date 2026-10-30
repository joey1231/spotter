import type { Plan, RouteResult } from "../lib/types";
import { RISK_COLOR, RISK_LABEL, RISK_LEVELS, ROUTE_COLOR } from "../lib/risk";
import { formatDuration, formatMiles, formatTime } from "../lib/format";

interface Props {
  plan: Plan;
  selected: string | null;
  onSelect: (id: string) => void;
}

function RiskBar({ route }: { route: RouteResult }) {
  const total = route.distance_mi || 1;
  return (
    <div className="risk-bar" aria-label="Miles by risk level">
      {RISK_LEVELS.map((level) => {
        const miles = route.miles_by_level[level];
        if (!miles) return null;
        return (
          <span
            key={level}
            style={{ width: `${(miles / total) * 100}%`, background: RISK_COLOR[level] }}
            title={`${RISK_LABEL[level]}: ${formatMiles(miles)}`}
          />
        );
      })}
      {route.unknown_miles > 0 && (
        <span style={{ width: `${(route.unknown_miles / total) * 100}%`, background: RISK_COLOR.unknown }} title="No forecast" />
      )}
    </div>
  );
}

export default function RouteCards({ plan, selected, onSelect }: Props) {
  const routes = [...plan.routes].sort((a, b) => a.rank - b.rank);
  const best = plan.recommendation.route_id;
  return (
    <section className="routes">
      <div className="recommendation">
        <div className="rec-title">
          Recommended: <b style={{ color: ROUTE_COLOR[best] }}>Route {best}</b>
        </div>
        <ul>
          {plan.recommendation.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>
      {plan.warnings.map((w) => (
        <div className="warning" key={w}>
          {w}
        </div>
      ))}
      <div className="cards">
        {routes.map((route) => {
          const m = route.miles_by_level;
          return (
            <button
              type="button"
              key={route.id}
              className={`card${selected === route.id ? " selected" : ""}`}
              onClick={() => onSelect(route.id)}
              aria-pressed={selected === route.id}
            >
              <div className="card-head">
                <span className="route-id" style={{ background: ROUTE_COLOR[route.id] }}>
                  {route.id}
                </span>
                <span className="roads" title={route.roads.join(", ")}>
                  via {route.roads.slice(0, 2).join(", ") || "local roads"}
                </span>
                {route.id === best ? <span className="pill best">★ Best</span> : <span className="pill">#{route.rank}</span>}
              </div>
              <div className="stats">
                <div>
                  <b>{formatDuration(route.trip_s)}</b>
                  <small>{route.stop_s > 0 ? `${formatDuration(route.drive_s)} driving` : "travel time"}</small>
                </div>
                <div>
                  <b>{formatMiles(route.distance_mi)}</b>
                  <small>distance</small>
                </div>
                <div>
                  <b>{formatTime(route.arrival_ts)}</b>
                  <small>arrival</small>
                </div>
              </div>
              <RiskBar route={route} />
              <div className="risk-miles">
                <span className={m.no_travel ? "hot" : ""} style={{ ["--c" as string]: RISK_COLOR.no_travel }}>
                  No travel <b>{Math.round(m.no_travel)}</b>
                </span>
                <span className={m.severe ? "hot" : ""} style={{ ["--c" as string]: RISK_COLOR.severe }}>
                  Severe <b>{Math.round(m.severe)}</b>
                </span>
                <span className={m.high ? "hot" : ""} style={{ ["--c" as string]: RISK_COLOR.high }}>
                  High <b>{Math.round(m.high)}</b>
                </span>
                <span>
                  Avg risk <b>{route.avg_risk.toFixed(2)}</b>
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
