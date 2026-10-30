import type { GeocodeResult, Heatmap, LngLat, Plan, PlanRequest } from "./types";

export class ApiError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Cannot reach the server. Check your connection and try again.");
  }
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(describeError(body) ?? `Request failed (HTTP ${resp.status}).`);
  return body as T;
}

/** Flatten DRF validation errors ({field: [msg]} or nested) into one sentence. */
function describeError(body: unknown, path = ""): string | null {
  if (!body) return null;
  if (typeof body === "string") return path ? `${path}: ${body}` : body;
  if (Array.isArray(body)) return describeError(body[0], path);
  if (typeof body === "object") {
    const obj = body as Record<string, unknown>;
    if (typeof obj.detail === "string") return obj.detail;
    const [key, value] = Object.entries(obj)[0] ?? [];
    if (key === undefined) return null;
    const label = key === "non_field_errors" ? path : key.replace(/_/g, " ");
    return describeError(value, label);
  }
  return null;
}

export function geocode(query: string, signal: AbortSignal): Promise<{ results: GeocodeResult[] }> {
  return request(`/api/geocode?q=${encodeURIComponent(query)}`, { signal });
}

export function planTrip(body: PlanRequest, signal?: AbortSignal): Promise<Plan> {
  return request("/api/plan", { method: "POST", body: JSON.stringify(body), signal });
}

export function fetchHeatmap(plan: Plan, signal?: AbortSignal): Promise<Heatmap> {
  // Thin each route to ≤400 vertices; the corridor is tens of miles wide, so
  // this loses nothing visible and keeps the request small.
  const routes: LngLat[][] = plan.routes.map((r) => {
    const step = Math.max(1, Math.floor(r.geometry.length / 400));
    const pts = r.geometry.filter((_, i) => i % step === 0);
    return [...pts, r.geometry[r.geometry.length - 1]];
  });
  return request("/api/heatmap", {
    method: "POST",
    body: JSON.stringify({ routes, departure: plan.departure, load_lb: plan.load_lb }),
    signal,
  });
}
