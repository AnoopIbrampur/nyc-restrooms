"""Export compact data for the static Phase 2 map (docs/map/).

Weekday view only (Wednesday of each reference week), three scenarios:
summer reading A, summer reading B, winter (A and B are identical in winter).
Minutes are rounded and capped: 0..60 real minutes, 61 = more than 60, 255 = no network.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from restrooms.deserts import restroom_sets
from restrooms.paths import DOCS, PROCESSED

WED = 2
SCENARIOS = {"summer_A": ("summer", "A"), "summer_B": ("summer", "B"), "winter": ("winter", "A")}


def _cap(m: np.ndarray) -> list[int]:
    out = np.where(np.isfinite(m), np.minimum(np.round(m), 61), 61).astype(int)
    return out.tolist()


def export() -> dict:
    hexes = pd.read_parquet(PROCESSED / "hexes.parquet")
    cols = slice(WED * 24, WED * 24 + 24)
    hex_vals = {}
    for key, (season, reading) in SCENARIOS.items():
        m = np.load(PROCESSED / f"hex_minutes_{season}_{reading}.npy")[:, cols]
        v = np.array(_cap(m))
        v[hexes["no_network"].to_numpy()] = 255
        hex_vals[key] = v.flatten().tolist()  # row-major: hex i, hour h -> i*24+h

    results = json.loads((DOCS / "phase2_results.json").read_text())
    st = pd.read_csv(DOCS / "phase2_station_table.csv")

    p = pd.read_parquet(PROCESSED / "places.parquet")
    prim = restroom_sets(p)["primary"]
    rows = (p["official_present"] & p["hours_summer"].notna()) | (
        (p["category"] == "amenity=toilets")
        & ~p["official_present"]
        & ~p["osm_access"].isin({"private", "no", "customers"})
        & (p["osm_fee"] != "yes")
        & (p["hours_source"] == "osm")
    )
    rp = p[rows].reset_index(drop=True)
    assert len(rp) == len(prim.lat)
    restrooms = []
    for i, r in rp.iterrows():
        open_bits = {
            k: "".join("1" if b else "0" for b in prim.masks[s][i, cols])
            for k, s in SCENARIOS.items()
        }
        restrooms.append(
            {
                "n": r["name"] if isinstance(r["name"], str) else "Public restroom",
                "t": r["official_location_type"]
                if isinstance(r["official_location_type"], str)
                else "OSM",
                "la": round(float(r["lat"]), 5),
                "lo": round(float(r["lon"]), 5),
                "h": r["hours_text"] if isinstance(r["hours_text"], str) else "",
                "o": open_bits,
            }
        )

    data = {
        "hours_note": "Wednesday of the reference weeks: summer 2026-07-15, winter 2027-01-27.",
        "hexes": hexes["h3"].tolist(),
        "hexMinutes": hex_vals,
        "profile": {
            "summer_A": results["hour_profile"]["summer_A"],
            "summer_B": results["hour_profile"]["summer_B"],
            "winter": results["hour_profile"]["winter_A"],
        },
        "stations": [
            {
                "n": r["station_complex"],
                "la": round(float(r["lat"]), 5),
                "lo": round(float(r["lon"]), 5),
                "e": int(r["weekday_entries"]),
                "s": int(r["stranded_entries_per_weekday"]),
            }
            for _, r in st.iterrows()
        ],
        "restrooms": restrooms,
    }
    out = DOCS / "map"
    out.mkdir(exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    size = (out / "data.json").stat().st_size
    print(f"wrote {out / 'data.json'} ({size / 1e6:.1f} MB)")
    return {"bytes": size}
