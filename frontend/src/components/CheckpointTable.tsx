import { memo } from "react";
import type { RouteResult } from "../lib/types";
import { RISK_COLOR, RISK_LABEL } from "../lib/risk";
import { formatPrecip, formatTime, localTz } from "../lib/format";

interface Props {
  route: RouteResult;
  intervalMi: number;
  onFocus: (index: number) => void;
}

function CheckpointTable({ route, intervalMi, onFocus }: Props) {
  return (
    <section className="checkpoints-panel">
      <h3>
        Route {route.id} checkpoints <small>every {intervalMi} mi · times in {localTz}</small>
      </h3>
      <div className="table-wrap">
        <table className="cp-table">
          <thead>
            <tr>
              <th>Mile</th>
              <th>ETA</th>
              <th title="Sustained wind (gust)">Wind mph</th>
              <th title="Rain in/hr">Rain</th>
              <th title="Snow in/hr">Snow</th>
              <th>Risk</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((cp, i) => {
              const level = cp.risk?.level;
              return (
                <tr key={i} onClick={() => onFocus(i)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onFocus(i)}>
                  <td>{Math.round(cp.mile)}</td>
                  <td className="nowrap">{formatTime(cp.eta_ts)}</td>
                  <td className={cp.risk && cp.risk.wind !== "low" ? "warn" : ""}>
                    {cp.weather ? (
                      <>
                        {cp.weather.wind_mph.toFixed(0)} <small>({cp.weather.gust_mph.toFixed(0)})</small>
                      </>
                    ) : (
                      "–"
                    )}
                  </td>
                  <td className={cp.risk && cp.risk.rain !== "low" ? "warn" : ""}>
                    {cp.weather ? formatPrecip(cp.weather.rain_in_hr) : "–"}
                  </td>
                  <td className={cp.risk && cp.risk.snow !== "low" ? "warn" : ""}>
                    {cp.weather ? formatPrecip(cp.weather.snow_in_hr) : "–"}
                  </td>
                  <td>
                    <span className="badge" style={{ ["--c" as string]: level ? RISK_COLOR[level] : RISK_COLOR.unknown }}>
                      {level ? RISK_LABEL[level] : "n/a"}
                      {cp.risk?.load_escalated ? " ⚖" : ""}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="footnote">⚖ = escalated by the heavy-load wind rules. Click a row to locate it on the map.</p>
    </section>
  );
}

export default memo(CheckpointTable);
