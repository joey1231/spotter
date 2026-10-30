import type { RiskKey } from "./types";

export const RISK_LEVELS: RiskKey[] = ["low", "moderate", "high", "severe", "no_travel"];

export const RISK_LABEL: Record<RiskKey, string> = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
  severe: "Severe",
  no_travel: "No Travel",
};

export const RISK_COLOR: Record<RiskKey | "unknown", string> = {
  low: "#16a34a",
  moderate: "#eab308",
  high: "#f97316",
  severe: "#dc2626",
  no_travel: "#7e22ce",
  unknown: "#94a3b8",
};

/** Identity colours for routes A/B/C, kept apart from the risk palette. */
export const ROUTE_COLOR: Record<string, string> = { A: "#2563eb", B: "#0e7490", C: "#6d28d9" };

/**
 * Heatmap weight for a 0–4 risk score. A small floor keeps calm weather faintly
 * visible so the corridor itself is always readable.
 */
export const HEAT_FLOOR = 0.05;
export const heatWeight = (score: number) => HEAT_FLOOR + ((1 - HEAT_FLOOR) * score) / 4;
