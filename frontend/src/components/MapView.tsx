import { useEffect, useRef, useState } from "react";
import maplibregl, { type ExpressionSpecification, type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Checkpoint, HeatMetric, Heatmap, Plan } from "../lib/types";
import { HEAT_FLOOR, RISK_COLOR, RISK_LABEL, ROUTE_COLOR } from "../lib/risk";
import { describeWeather, formatDuration, formatMiles, formatPrecip, formatTime } from "../lib/format";

const STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export interface MapFocus {
  routeId: string;
  index: number;
  nonce: number;
}

interface Props {
  plan: Plan | null;
  heatmap: Heatmap | null;
  selectedRoute: string | null;
  onSelectRoute: (id: string) => void;
  hour: number;
  metric: HeatMetric;
  showHeatmap: boolean;
  focus: MapFocus | null;
}

const riskColorExpr: ExpressionSpecification = [
  "match",
  ["get", "level"],
  "low", RISK_COLOR.low,
  "moderate", RISK_COLOR.moderate,
  "high", RISK_COLOR.high,
  "severe", RISK_COLOR.severe,
  "no_travel", RISK_COLOR.no_travel,
  RISK_COLOR.unknown,
];

const routeColorExpr: ExpressionSpecification = [
  "match", ["get", "route"], "A", ROUTE_COLOR.A, "B", ROUTE_COLOR.B, ROUTE_COLOR.C,
];

/** Property key holding a metric's score for a given hour, e.g. "r12". */
const heatKey = (metric: HeatMetric, hour: number) => `${metric[0]}${hour}`;

function heatWeightExpr(metric: HeatMetric, hour: number): ExpressionSpecification {
  // Hours beyond the forecast window are null → weight 0 (transparent).
  const value: ExpressionSpecification = ["to-number", ["coalesce", ["get", heatKey(metric, hour)], -1]];
  return ["case", [">=", value, 0], ["+", HEAT_FLOOR, ["*", (1 - HEAT_FLOOR) / 4, value]], 0];
}

/**
 * Kernel radius tied to the grid spacing so the blur is resolution-independent:
 * each point's kernel spans ~2 cells, which makes overlapping kernels sum to
 * roughly the point weight (calibrated with heatmap-intensity below).
 */
function heatRadiusExpr(cellDeg: number): ExpressionSpecification {
  const pxAtZ0 = 2 * cellDeg * (512 / 360);
  return ["interpolate", ["exponential", 2], ["zoom"], 0, pxAtZ0, 12, pxAtZ0 * 2 ** 12];
}

function el(className: string, html: string): HTMLDivElement {
  const div = document.createElement("div");
  div.className = className;
  div.innerHTML = html;
  return div;
}

function checkpointPopupHtml(routeId: string, cp: Checkpoint, index: number, total: number): string {
  const w = cp.weather;
  const r = cp.risk;
  const level = r?.level ?? null;
  const badge = level
    ? `<span class="badge" style="--c:${RISK_COLOR[level]}">${RISK_LABEL[level]}</span>`
    : `<span class="badge" style="--c:${RISK_COLOR.unknown}">No forecast</span>`;
  const why =
    r && r.drivers.length
      ? `<div class="pop-why">Driven by ${r.drivers.join(" + ")}${r.load_escalated ? " (escalated by load weight)" : ""}</div>`
      : "";
  const place = index === 0 ? "Origin" : index === total - 1 ? "Destination" : `Checkpoint ${index}`;
  return `
    <div class="pop">
      <div class="pop-head"><b>Route ${routeId}</b> · ${place} ${badge}</div>
      <div class="pop-sub">Mile ${cp.mile.toFixed(0)} · ETA ${formatTime(cp.eta_ts)}</div>
      ${
        w
          ? `<table class="pop-grid">
              <tr><td>Wind</td><td>${w.wind_mph.toFixed(0)} mph <span class="muted">gust ${w.gust_mph.toFixed(0)}</span></td></tr>
              <tr><td>Rain</td><td>${formatPrecip(w.rain_in_hr)} in/hr</td></tr>
              <tr><td>Snow</td><td>${formatPrecip(w.snow_in_hr)} in/hr</td></tr>
              <tr><td>Sky</td><td>${describeWeather(w.weather_code)}${w.temp_f != null ? `, ${w.temp_f}°F` : ""}</td></tr>
            </table>`
          : `<div class="muted">ETA is beyond the forecast window.</div>`
      }
      ${why}
    </div>`;
}

export default function MapView({ plan, heatmap, selectedRoute, onSelectRoute, hour, metric, showHeatmap, focus }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const trucksRef = useRef<Map<string, maplibregl.Marker>>(new Map());
  const onSelectRef = useRef(onSelectRoute);
  const planRef = useRef(plan);
  const [ready, setReady] = useState(false);

  onSelectRef.current = onSelectRoute;
  planRef.current = plan;

  // --- One-time map setup --------------------------------------------------
  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current!,
      style: STYLE_URL,
      center: [-96, 38.5],
      zoom: 3.6,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as unknown as { __map: maplibregl.Map }).__map = map; // for debugging/calibration
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // Top-left keeps attribution clear of the heatmap panel docked at the bottom.
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "top-left");
    map.touchZoomRotate.disableRotation();
    popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: "280px", offset: 10 });

    map.on("load", () => {
      // Draw the heatmap beneath the basemap's labels so place names stay legible.
      const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;

      map.addSource("heat", { type: "geojson", data: EMPTY });
      map.addLayer(
        {
          id: "heat",
          type: "heatmap",
          source: "heat",
          paint: {
            "heatmap-weight": heatWeightExpr("risk", 0),
            // Calibrated so the summed kernels of a uniform grid ≈ the point weight,
            // i.e. a High-risk area actually renders in the High colour.
            "heatmap-intensity": 0.8,
            "heatmap-radius": heatRadiusExpr(0.5),
            "heatmap-opacity": 0.8,
            "heatmap-color": [
              "interpolate", ["linear"], ["heatmap-density"],
              0, "rgba(0,0,0,0)",
              0.02, "rgba(22,163,74,0)",
              0.05, "rgba(22,163,74,0.28)",
              0.25, "rgba(22,163,74,0.36)",
              0.2875, "rgba(234,179,8,0.55)",
              0.525, "rgba(249,115,22,0.65)",
              0.7625, "rgba(220,38,38,0.7)",
              1, "rgba(126,34,206,0.75)",
            ],
          },
        },
        firstLabel,
      );

      map.addSource("routes", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "route-other",
        type: "line",
        source: "routes",
        filter: ["all", ["==", ["get", "kind"], "full"], ["!=", ["get", "route"], ""]],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": routeColorExpr, "line-width": 4, "line-opacity": 0.55 },
      });
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: "routes",
        filter: ["==", ["get", "kind"], "none"],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#0f172a", "line-width": 10, "line-opacity": 0.85 },
      });
      map.addLayer({
        id: "route-risk",
        type: "line",
        source: "routes",
        filter: ["==", ["get", "kind"], "none"],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": riskColorExpr, "line-width": 6 },
      });

      map.addSource("checkpoints", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "checkpoints-other",
        type: "circle",
        source: "checkpoints",
        filter: ["==", ["get", "route"], "none"],
        paint: {
          "circle-radius": 3.5,
          "circle-color": riskColorExpr,
          "circle-opacity": 0.7,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 1,
        },
      });
      map.addLayer({
        id: "checkpoints",
        type: "circle",
        source: "checkpoints",
        filter: ["==", ["get", "route"], "none"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 5, 9, 8],
          "circle-color": riskColorExpr,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });

      const showCheckpoint = (e: maplibregl.MapLayerMouseEvent) => {
        const props = e.features?.[0]?.properties;
        const route = planRef.current?.routes.find((r) => r.id === props?.route);
        if (!props || !route) return;
        const cp = route.checkpoints[props.index];
        popupRef.current!
          .setLngLat(cp.coordinates)
          .setHTML(checkpointPopupHtml(route.id, cp, props.index, route.checkpoints.length))
          .addTo(map);
      };
      map.on("click", "checkpoints", showCheckpoint);
      map.on("click", "checkpoints-other", (e) => {
        showCheckpoint(e);
        const id = e.features?.[0]?.properties?.route;
        if (id) onSelectRef.current(id);
      });
      map.on("click", "route-other", (e) => {
        const hitsCheckpoint = map.queryRenderedFeatures(e.point, { layers: ["checkpoints", "checkpoints-other"] });
        const id = e.features?.[0]?.properties?.route;
        if (id && !hitsCheckpoint.length) onSelectRef.current(id);
      });
      for (const layer of ["checkpoints", "checkpoints-other", "route-other"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
      }
      setReady(true);
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // --- Plan: routes, checkpoints, markers ----------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];
    trucksRef.current.forEach((m) => m.remove());
    trucksRef.current.clear();
    popupRef.current?.remove();

    const routes = map.getSource("routes") as GeoJSONSource;
    const checkpoints = map.getSource("checkpoints") as GeoJSONSource;
    if (!plan) {
      routes.setData(EMPTY);
      checkpoints.setData(EMPTY);
      return;
    }

    const lineFeatures: GeoJSON.Feature[] = [];
    const pointFeatures: GeoJSON.Feature[] = [];
    for (const route of plan.routes) {
      lineFeatures.push({
        type: "Feature",
        properties: { kind: "full", route: route.id },
        geometry: { type: "LineString", coordinates: route.geometry },
      });
      for (const seg of route.segments) {
        lineFeatures.push({
          type: "Feature",
          properties: { kind: "risk", route: route.id, level: seg.level },
          geometry: { type: "LineString", coordinates: seg.coordinates },
        });
      }
      route.checkpoints.forEach((cp, index) => {
        pointFeatures.push({
          type: "Feature",
          properties: { route: route.id, index, level: cp.risk?.level ?? "unknown" },
          geometry: { type: "Point", coordinates: cp.coordinates },
        });
      });
    }
    routes.setData({ type: "FeatureCollection", features: lineFeatures });
    checkpoints.setData({ type: "FeatureCollection", features: pointFeatures });

    const addMarker = (lngLat: [number, number], node: HTMLElement, anchor: maplibregl.PositionAnchor = "center") => {
      const marker = new maplibregl.Marker({ element: node, anchor }).setLngLat(lngLat).addTo(map);
      markersRef.current.push(marker);
      return marker;
    };
    addMarker(plan.origin.coordinates, el("pin pin-origin", "<span>S</span>"), "bottom").setPopup(
      new maplibregl.Popup({ offset: 24 }).setText(`Start: ${plan.origin.label}`),
    );
    addMarker(plan.destination.coordinates, el("pin pin-dest", "<span>E</span>"), "bottom").setPopup(
      new maplibregl.Popup({ offset: 24 }).setText(`End: ${plan.destination.label}`),
    );

    // Route summary labels, staggered along each route so they don't stack.
    plan.routes.forEach((route, i) => {
      const cps = route.checkpoints;
      const at = cps[Math.floor((cps.length - 1) * (0.3 + 0.2 * i))].coordinates;
      const best = plan.recommendation.route_id === route.id;
      const label = el(
        `route-label${best ? " best" : ""}`,
        `<b style="background:${ROUTE_COLOR[route.id]}">${route.id}</b>
         <span>${formatDuration(route.trip_s)} · ${formatMiles(route.distance_mi)}${best ? " · ★" : ""}</span>`,
      );
      label.dataset.route = route.id;
      label.title = `Select Route ${route.id}`;
      label.addEventListener("click", (e) => {
        e.stopPropagation();
        onSelectRef.current(route.id);
      });
      addMarker(at, label);

      const truck = el("truck", `<span style="background:${ROUTE_COLOR[route.id]}">${route.id}</span>`);
      truck.dataset.route = route.id;
      trucksRef.current.set(route.id, new maplibregl.Marker({ element: truck }).setLngLat(route.hourly_positions[0]).addTo(map));
    });

    const bounds = new maplibregl.LngLatBounds();
    plan.routes.forEach((r) => r.geometry.forEach((p) => bounds.extend(p)));
    const narrow = map.getContainer().clientWidth < 700;
    map.fitBounds(bounds, { padding: narrow ? 40 : { top: 60, bottom: 150, left: 60, right: 60 }, duration: 900 });
  }, [plan, ready]);

  // --- Selection: cheap filter swaps, no data re-upload ---------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const sel = selectedRoute ?? "none";
    map.setFilter("route-other", ["all", ["==", ["get", "kind"], "full"], ["!=", ["get", "route"], sel]]);
    map.setFilter("route-casing", ["all", ["==", ["get", "kind"], "full"], ["==", ["get", "route"], sel]]);
    map.setFilter("route-risk", ["all", ["==", ["get", "kind"], "risk"], ["==", ["get", "route"], sel]]);
    map.setFilter("checkpoints", ["==", ["get", "route"], sel]);
    map.setFilter("checkpoints-other", ["!=", ["get", "route"], sel]);
    for (const m of markersRef.current) {
      const node = m.getElement();
      if (node.dataset.route) node.classList.toggle("selected", node.dataset.route === selectedRoute);
    }
    trucksRef.current.forEach((m, id) => m.getElement().classList.toggle("selected", id === selectedRoute));
  }, [selectedRoute, ready, plan]);

  // --- Heatmap data ---------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource("heat") as GeoJSONSource;
    if (!heatmap) {
      source.setData(EMPTY);
      return;
    }
    // Flatten every metric/hour into feature properties once, so moving the
    // slider is just a paint-property change evaluated on the GPU.
    const metrics = Object.keys(heatmap.values) as HeatMetric[];
    const features: GeoJSON.Feature[] = heatmap.points.map((point, i) => {
      const properties: Record<string, number | null> = {};
      for (const m of metrics) {
        heatmap.values[m][i].forEach((v, h) => (properties[heatKey(m, h)] = v));
      }
      return { type: "Feature", properties, geometry: { type: "Point", coordinates: point } };
    });
    source.setData({ type: "FeatureCollection", features });
    map.setPaintProperty("heat", "heatmap-radius", heatRadiusExpr(heatmap.cell_deg));
  }, [heatmap, ready]);

  // --- Slider hour / metric -------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setPaintProperty("heat", "heatmap-weight", heatWeightExpr(metric, hour));
    plan?.routes.forEach((route) => {
      const pos = route.hourly_positions[Math.min(hour, route.hourly_positions.length - 1)];
      trucksRef.current.get(route.id)?.setLngLat(pos);
    });
  }, [hour, metric, ready, plan]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.setLayoutProperty("heat", "visibility", showHeatmap ? "visible" : "none");
  }, [showHeatmap, ready]);

  // --- Focus a checkpoint (from the table) -----------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus || !plan) return;
    const route = plan.routes.find((r) => r.id === focus.routeId);
    const cp = route?.checkpoints[focus.index];
    if (!route || !cp) return;
    map.flyTo({ center: cp.coordinates, zoom: Math.max(map.getZoom(), 7), duration: 700 });
    popupRef.current!
      .setLngLat(cp.coordinates)
      .setHTML(checkpointPopupHtml(route.id, cp, focus.index, route.checkpoints.length))
      .addTo(map);
  }, [focus, ready, plan]);

  return <div ref={containerRef} className="map" />;
}
