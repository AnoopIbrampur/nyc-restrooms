"""Seed data for the API's `places` table: the Phase 3 universe of businesses where a
delivery worker might pick up (restaurants, groceries, shops, services...)."""

from __future__ import annotations

import h3
import pandas as pd

from restrooms.audit import universe
from restrooms.paths import ROOT

SEED = ROOT / "backend" / "seed" / "places.sql"


def _q(s: object) -> str:
    if s is None or pd.isna(s):
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def write_seed(batch: int = 500) -> int:
    u = universe()
    u = u[u["place_id"].str.match(r"^(osm:(node|way):\d+|dohmh:\d+)$")]
    SEED.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in u.itertuples():
        cell = h3.latlng_to_cell(r.lat, r.lon, 7)
        rows.append(f"({_q(r.place_id)},{_q(r.name)},{r.lat:.6f},{r.lon:.6f},{_q(cell)})")
    with open(SEED, "w") as f:
        f.write("DELETE FROM places;\n")
        for i in range(0, len(rows), batch):
            f.write("INSERT INTO places (place_id,name,lat,lon,cell7) VALUES\n")
            f.write(",\n".join(rows[i : i + batch]) + ";\n")
    print(f"wrote {SEED} ({len(rows)} places)")
    return len(rows)
