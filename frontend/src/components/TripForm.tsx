import { useState } from "react";
import PlaceInput from "./PlaceInput";
import { nextHourLocalInput } from "../lib/format";
import type { PlanRequest, Place } from "../lib/types";

interface Props {
  loading: boolean;
  onSubmit: (req: PlanRequest) => void;
}

const INTERVALS = [10, 25, 50] as const;

export default function TripForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place>({ label: "Chicago, Illinois, US", lat: 41.8755616, lon: -87.6244212 });
  const [destination, setDestination] = useState<Place>({ label: "Denver, Colorado, US", lat: 39.7392364, lon: -104.984862 });
  const [departure, setDeparture] = useState(nextHourLocalInput);
  const [load, setLoad] = useState("42000");
  const [intervalMi, setIntervalMi] = useState<(typeof INTERVALS)[number]>(25);
  const [hos, setHos] = useState(true);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      origin,
      destination,
      // datetime-local is wall-clock time in the browser's zone; send an absolute instant.
      departure: new Date(departure).toISOString(),
      load_lb: Number(load),
      interval_mi: intervalMi,
      apply_hos: hos,
    });
  };

  const swap = () => {
    setOrigin(destination);
    setDestination(origin);
  };

  return (
    <form className="trip-form" onSubmit={submit}>
      <div className="places">
        <PlaceInput label="Origin" value={origin} onChange={setOrigin} placeholder="City or address" />
        <button type="button" className="swap" onClick={swap} title="Swap origin and destination" aria-label="Swap">
          ⇅
        </button>
        <PlaceInput label="Destination" value={destination} onChange={setDestination} placeholder="City or address" />
      </div>
      <div className="row">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input id="departure" type="datetime-local" required value={departure} onChange={(e) => setDeparture(e.target.value)} />
        </div>
        <div className="field narrow">
          <label htmlFor="load">Load (lb)</label>
          <input
            id="load"
            type="number"
            min={0}
            max={200000}
            step={500}
            required
            value={load}
            onChange={(e) => setLoad(e.target.value)}
          />
        </div>
      </div>
      <div className="row align-end">
        <div className="field">
          <span className="label">Weather sample every</span>
          <div className="segmented" role="radiogroup" aria-label="Sampling interval">
            {INTERVALS.map((v) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={intervalMi === v}
                className={intervalMi === v ? "on" : ""}
                onClick={() => setIntervalMi(v)}
              >
                {v} mi
              </button>
            ))}
          </div>
        </div>
        <label className="check" title="Insert FMCSA 30-min breaks and 10-h rests into ETAs">
          <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
          HOS stops
        </label>
      </div>
      <button className="primary" type="submit" disabled={loading}>
        {loading ? "Planning…" : "Plan routes"}
      </button>
    </form>
  );
}
