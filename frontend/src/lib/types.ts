// Mirrors the Django API payloads (planner/services/planner.py, corridor.py).

export type RiskKey = "low" | "moderate" | "high" | "severe" | "no_travel";
export type LngLat = [number, number];

export interface Place {
  label: string;
  lat?: number;
  lon?: number;
}

export interface PlanRequest {
  origin: Place;
  destination: Place;
  departure: string;
  load_lb: number;
  interval_mi: 10 | 25 | 50;
  apply_hos: boolean;
}

export interface Weather {
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
  temp_f: number | null;
  weather_code: number | null;
}

export interface CheckpointRisk {
  level: RiskKey;
  score: number;
  wind: RiskKey;
  rain: RiskKey;
  snow: RiskKey;
  drivers: string[];
  load_escalated: boolean;
}

export interface Checkpoint {
  mile: number;
  coordinates: LngLat;
  eta: string;
  eta_ts: number;
  drive_s: number;
  span_miles: number;
  weather: Weather | null;
  risk: CheckpointRisk | null;
}

export interface RouteResult {
  id: string;
  rank: number;
  roads: string[];
  distance_mi: number;
  drive_s: number;
  trip_s: number;
  stop_s: number;
  arrival: string;
  arrival_ts: number;
  miles_by_level: Record<RiskKey, number>;
  unknown_miles: number;
  avg_risk: number;
  max_level: RiskKey;
  geometry: LngLat[];
  segments: { level: RiskKey | "unknown"; coordinates: LngLat[] }[];
  checkpoints: Checkpoint[];
  hourly_positions: LngLat[];
}

export interface Plan {
  departure: string;
  departure_ts: number;
  load_lb: number;
  interval_mi: number;
  apply_hos: boolean;
  origin: { label: string; coordinates: LngLat };
  destination: { label: string; coordinates: LngLat };
  routes: RouteResult[];
  recommendation: { route_id: string; ranking: string[]; reasons: string[] };
  warnings: string[];
}

export type HeatMetric = "risk" | "wind" | "rain" | "snow";

export interface Heatmap {
  hours: number[];
  cell_deg: number;
  points: LngLat[];
  values: Record<HeatMetric, (number | null)[][]>;
}

export interface GeocodeResult {
  label: string;
  lat: number;
  lon: number;
}
