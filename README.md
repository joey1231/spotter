# Weather-Aware Truck Routing

A React + Django app that plans three truck routes between two places, samples the forecast at
each checkpoint **at the time the truck is expected to be there**, classifies risk with the
provided wind/rain/snow + load-weight rules, and recommends the safest route.

- **Live app:** _add hosted URL_
- **Walkthrough:** _add Loom URL_

No API keys are needed: routing uses OSRM, weather uses Open-Meteo and place search uses Photon.

## Run locally

```bash
# Backend (Python 3.10+)
cd backend
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py test planner                         # 26 unit tests
python manage.py runserver 8000

# Frontend (Node 20+), in a second terminal
cd frontend
npm install
npm run dev                                           # http://localhost:5173, proxies /api → :8000
# if the API runs on another port: API_URL=http://127.0.0.1:8010 npm run dev
```

**Production** runs as one container: `docker build -t truck-routing . && docker run -p 8000:8000 truck-routing`.
Django serves the API and WhiteNoise serves the built SPA from the same origin. `render.yaml` deploys it to
Render as-is (New → Blueprint → pick the repo).

## How it works

```
POST /api/plan  ─► routing.find_routes ─► 3 routes (OSRM)
                    planner: checkpoints every 10/25/50 mi, ETA = departure + truck drive time + HOS stops
                    weather.forecasts: hourly series per checkpoint (batched, cached)
                    risk.assess at each checkpoint's ETA ─► miles per level ─► recommend.rank
POST /api/heatmap ─► corridor grid around the routes ─► 49 hourly risk scores per grid point
```

| Concern | Where | Notes |
|---|---|---|
| Risk table and load rules | [`risk.py`](backend/planner/services/risk.py) | Pure functions, unit-tested at every boundary |
| Ranking | [`recommend.py`](backend/planner/services/recommend.py) | Lexicographic, produces a written reason per runner-up |
| Routes | [`routing.py`](backend/planner/services/routing.py) | OSRM alternatives, plus via-point fallback |
| ETAs | [`hos.py`](backend/planner/services/hos.py), [`planner.py`](backend/planner/services/planner.py) | Truck speed cap, HOS breaks and rests |
| Weather | [`weather.py`](backend/planner/services/weather.py) | Open-Meteo, cached per 0.1° cell |
| Heatmap | [`corridor.py`](backend/planner/services/corridor.py), [`MapView.tsx`](frontend/src/components/MapView.tsx) | GPU heatmap layer |

### Three routes
OSRM's `alternatives` often returns only 1–2 routes on long trips. When that happens, the backend asks for
routes forced through via-points offset to either side of the fastest route (12% and 22% of the trip length,
at 35/50/65% of the way along). It keeps a candidate only if:

- it overlaps every kept route by **≤ 80%**,
- it is **≤ 45% slower** than the fastest route, and
- it has no out-and-back spur (a detour that drives to the via-point and straight back).

### Checkpoints and ETAs
- Checkpoints sit at the origin, every N miles (10/25/50), and the destination.
- Each checkpoint **represents the miles nearer to it than to its neighbours**, so per-level miles add up
  exactly to the route length.
- **Drive time** is OSRM's per-segment duration, capped at 65 mph (`TRUCK_MAX_SPEED_MPH`), because OSRM
  uses car speeds.
- **ETA** adds the federal hours-of-service (HOS) stops a solo driver must take: a 30-minute break after 8 h
  of driving and a 10-hour rest after 11 h. The *HOS stops* toggle turns this off.
- At each ETA, wind is interpolated between hours. Rain and snow come from the hourly total that covers the ETA.

### Risk rules (as specified)
| | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | <25 | 25–34 | 35–44 | 45–54 | ≥55 |
| Rain (in/hr) | <0.10 | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00 |
| Snow (in/hr) | <0.5 | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | >3.0 |

- Load rules: 45–54 mph with **>30,000 lb** → No Travel; 35–44 mph with **>40,000 lb** → Severe.
- Checkpoint risk is the worst of the three conditions.
- Wind uses sustained 10 m wind; gusts are shown but not scored.
- Rain counts both rain and showers.

**Boundary choices.** The table's ranges share their edges (rain "0.10–0.25" and "0.25–0.50"). I made every
band lower-inclusive, so a value on a shared edge goes to the *more severe* band. The No Travel edge follows
the table literally: wind ≥ 55, rain > 1.00, snow > 3.0.

### Recommendation
Routes are compared in this order:

1. **No Travel miles** (added by me: No Travel is above Severe in the table, so a route crossing a
   closure can never win)
2. Severe miles
3. High miles
4. Average risk (mile-weighted, Low = 0 … No Travel = 4)
5. Travel time

Ties use small tolerances (1 mile, 0.02 average risk) so forecast noise can't beat a meaningfully faster route.
The UI shows which criterion decided each comparison, e.g. *"Beats Route B on fewer High miles (0 vs 25 mi)."*

### Heatmap (0–48 h slider)
- **Grid.** The backend builds a grid that is square on the map, masked to a 25–60 mi buffer around the
  routes. Cell size grows with trip length to cap it at about 350 forecast points. For each point it returns
  continuous 0–4 risk scores for departure + 0…48 h (overall, wind, rain and snow). Each score's integer
  part equals the risk level, so heatmap colours match the level colours.
- **Smoothness.** Every hour is packed into feature properties once, so moving the slider only swaps a
  `heatmap-weight` paint expression on the GPU: no data re-upload and no React re-render of the map.
  Kernel radius scales with grid spacing and zoom, and intensity is calibrated so overlapping kernels sum
  to roughly the point's own weight. A High-risk area therefore renders in the High colour at any zoom.
- **Trucks.** Lettered markers show where each truck is at the selected hour, parked during HOS rests.

### Performance and limits
- Forecasts are cached for 30 min per 0.1° cell and routes for 15 min. The three routes and the heatmap
  overlap heavily, so they share forecast fetches. Repeat plans return in about 1 s.
- A cold plan takes about 10–18 s, mostly the public OSRM demo server. Point `OSRM_BASE_URL` at a self-hosted
  OSRM for production. Open-Meteo's free tier is about 10k location-calls/day; set `OPEN_METEO_API_KEY` for
  the commercial endpoint.
- Departures are limited to the next 10 days (14-day forecast horizon). Miles beyond the forecast are
  reported as unscored.
- Not modelled: truck-specific road restrictions (OSRM's car profile), the 14-hour on-duty window (it never
  binds for continuous driving), and gust-based scoring.
