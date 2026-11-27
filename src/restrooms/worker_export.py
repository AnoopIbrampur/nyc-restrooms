"""Data for the delivery-worker page (web/worker/, NOT published until approved).

- restrooms.json: primary-set restrooms (Phase 2) with full summer/winter weekly masks
  under reading A (the conservative one: "open later seasonally" closes at 4 pm).
- reports_public.json: output of reports.public_summary() over the stored reports.
  There is no report store yet (Phase 5), so this is the empty summary.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from restrooms.deserts import public_osm_toilets, restroom_sets
from restrooms.paths import PROCESSED, ROOT
from restrooms.reports import public_summary

OUT = ROOT / "web" / "worker"


def export(today: date | None = None) -> dict:
    today = today or date.today()
    p = pd.read_parquet(PROCESSED / "places.parquet")
    prim = restroom_sets(p)["primary"]
    rows = (p["official_present"] & p["hours_summer"].notna()) | (
        public_osm_toilets(p) & (p["hours_source"] == "osm")
    )
    rp = p[rows].reset_index(drop=True)
    assert len(rp) == len(prim.lat)
    ms, mw = prim.masks[("summer", "A")], prim.masks[("winter", "A")]
    bits = lambda row: "".join("1" if b else "0" for b in row)  # noqa: E731
    restrooms = []
    for i, r in rp.iterrows():
        if not ms[i].any() and not mw[i].any():
            continue  # closed in both seasons (not operational): never "open now"
        restrooms.append(
            {
                "n": r["name"] if isinstance(r["name"], str) else "Public restroom",
                "t": r["official_location_type"]
                if isinstance(r["official_location_type"], str)
                else "Public toilet (OpenStreetMap)",
                "la": round(float(r["lat"]), 5),
                "lo": round(float(r["lon"]), 5),
                "h": r["hours_text"] if isinstance(r["hours_text"], str) else "",
                "s": bits(ms[i]),
                "w": bits(mw[i]),
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "restrooms.json").write_text(json.dumps(restrooms, separators=(",", ":")))
    summary = public_summary([], p[["place_id", "name", "lat", "lon"]], today)
    (OUT / "reports_public.json").write_text(json.dumps(summary, indent=1))
    info = {"restrooms": len(restrooms), "bytes": (OUT / "restrooms.json").stat().st_size}
    print(info)
    return info
