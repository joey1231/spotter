import { useEffect, useId, useRef, useState } from "react";
import { geocode } from "../lib/api";
import type { GeocodeResult, Place } from "../lib/types";

interface Props {
  label: string;
  value: Place;
  onChange: (place: Place) => void;
  placeholder?: string;
}

/** Type-ahead place search. Free text is still accepted (geocoded server-side). */
export default function PlaceInput({ label, value, onChange, placeholder }: Props) {
  const id = useId();
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const picked = value.lat != null;
  const blurTimer = useRef<number>();

  useEffect(() => {
    const query = value.label.trim();
    if (picked || query.length < 3) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      geocode(query, controller.signal)
        .then((r) => {
          setResults(r.results);
          setActive(-1);
        })
        .catch(() => setResults([]));
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [value.label, picked]);

  const choose = (r: GeocodeResult) => {
    onChange({ label: r.label, lat: r.lat, lon: r.lon });
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? results.length - 1 : a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && results.length > 0;
  return (
    <div className="field place">
      <label htmlFor={id}>{label}</label>
      <div className="place-box">
        <input
          id={id}
          value={value.label}
          placeholder={placeholder}
          autoComplete="off"
          role="combobox"
          aria-expanded={showList}
          aria-controls={`${id}-list`}
          aria-activedescendant={active >= 0 ? `${id}-${active}` : undefined}
          onChange={(e) => {
            onChange({ label: e.target.value });
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => (blurTimer.current = window.setTimeout(() => setOpen(false), 150))}
          onKeyDown={onKeyDown}
        />
        {picked && <span className="place-ok" title="Location confirmed">✓</span>}
      </div>
      {showList && (
        <ul className="suggestions" id={`${id}-list`} role="listbox">
          {results.map((r, i) => (
            <li
              key={`${r.label}-${i}`}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                window.clearTimeout(blurTimer.current);
                choose(r);
              }}
            >
              {r.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
