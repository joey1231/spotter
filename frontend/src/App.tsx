import { useCallback, useEffect, useRef, useState } from "react";
import TripForm from "./components/TripForm";
import RouteCards from "./components/RouteCards";
import CheckpointTable from "./components/CheckpointTable";
import HeatmapPanel from "./components/HeatmapPanel";
import MapView, { type MapFocus } from "./components/MapView";
import { fetchHeatmap, planTrip } from "./lib/api";
import type { HeatMetric, Heatmap, Plan, PlanRequest } from "./lib/types";

export default function App() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [heatLoading, setHeatLoading] = useState(false);
  const [heatError, setHeatError] = useState<string | null>(null);
  const [hour, setHour] = useState(0);
  const [metric, setMetric] = useState<HeatMetric>("risk");
  const [showHeat, setShowHeat] = useState(true);
  const [playing, setPlaying] = useState(false);

  const [focus, setFocus] = useState<MapFocus | null>(null);
  const planAbort = useRef<AbortController>();

  const submit = useCallback(async (req: PlanRequest) => {
    planAbort.current?.abort();
    const controller = new AbortController();
    planAbort.current = controller;
    setPlanning(true);
    setPlanError(null);
    try {
      const result = await planTrip(req, controller.signal);
      setPlan(result);
      setSelected(result.recommendation.route_id);
      setHeatmap(null);
      setHour(0);
      setPlaying(false);
    } catch (err) {
      if ((err as Error).name !== "AbortError") setPlanError((err as Error).message);
    } finally {
      if (planAbort.current === controller) setPlanning(false);
    }
  }, []);

  // The heatmap is fetched after the plan so routes appear without waiting for it.
  useEffect(() => {
    if (!plan) return;
    const controller = new AbortController();
    setHeatLoading(true);
    setHeatError(null);
    fetchHeatmap(plan, controller.signal)
      .then(setHeatmap)
      .catch((err) => {
        if (err.name !== "AbortError") setHeatError(err.message);
      })
      .finally(() => !controller.signal.aborted && setHeatLoading(false));
    return () => controller.abort();
  }, [plan]);

  const selectedRoute = plan?.routes.find((r) => r.id === selected) ?? null;
  const focusCheckpoint = useCallback(
    (index: number) => selected && setFocus({ routeId: selected, index, nonce: Date.now() }),
    [selected],
  );

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="brand">
          <div className="logo" aria-hidden>
            ⛟
          </div>
          <div>
            <h1>Weather-Aware Truck Routing</h1>
            <p>Three routes, scored on forecast weather at each checkpoint's ETA.</p>
          </div>
        </header>
        <TripForm loading={planning} onSubmit={submit} />
        {planError && (
          <div className="error" role="alert">
            {planError}
          </div>
        )}
        {planning && !plan && <div className="placeholder">Finding routes and sampling weather along each one…</div>}
        {!plan && !planning && (
          <div className="placeholder">
            Enter a trip and press <b>Plan routes</b>. Each route is sampled every 10/25/50 miles using the truck's
            estimated arrival time at that point, then classified with the wind/rain/snow and load-weight rules.
          </div>
        )}
        {plan && (
          <div className={planning ? "stale" : ""}>
            <RouteCards plan={plan} selected={selected} onSelect={setSelected} />
            {selectedRoute && (
              <CheckpointTable route={selectedRoute} intervalMi={plan.interval_mi} onFocus={focusCheckpoint} />
            )}
          </div>
        )}
      </aside>
      <main className="map-area">
        <MapView
          plan={plan}
          heatmap={heatmap}
          selectedRoute={selected}
          onSelectRoute={setSelected}
          hour={hour}
          metric={metric}
          showHeatmap={showHeat}
          focus={focus}
        />
        {planning && <div className="map-busy">Planning…</div>}
        {plan && (
          <HeatmapPanel
            departureTs={plan.departure_ts}
            hour={hour}
            onHour={setHour}
            metric={metric}
            onMetric={setMetric}
            visible={showHeat}
            onVisible={setShowHeat}
            playing={playing}
            onPlaying={setPlaying}
            loading={heatLoading}
            error={heatError}
          />
        )}
      </main>
    </div>
  );
}
