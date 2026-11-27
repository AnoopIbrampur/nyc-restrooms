"""Phase 3 audit sample: 25 places per group + 15 ordered reserves, seeded (pre-registered)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from restrooms.categories import GROUPS, harmonize
from restrooms.ingest import load_raw
from restrooms.paths import DOCS, PROCESSED

SEED = 20261127
PER_GROUP = 25
RESERVES = 15
SHEET = DOCS / "phase3_audit_sheet.csv"
FILL = ["outcome", "answer", "method", "checked_on", "notes"]


def universe(p: pd.DataFrame | None = None) -> pd.DataFrame:
    p = pd.read_parquet(PROCESSED / "places.parquet") if p is None else p
    h = harmonize(p)
    return h[h["group"].notna()].sort_values("place_id").reset_index(drop=True)


def draw(u: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for g in GROUPS:
        pool = u[u["group"] == g]
        idx = rng.choice(len(pool), PER_GROUP + RESERVES, replace=False)
        take = pool.iloc[idx].copy()
        take["reserve_rank"] = [0] * PER_GROUP + list(range(1, RESERVES + 1))
        parts.append(take)
    s = pd.concat(parts, ignore_index=True)
    s.insert(0, "audit_id", [f"A{i:03d}" for i in range(1, len(s) + 1)])
    return s


def _contact(s: pd.DataFrame) -> pd.DataFrame:
    """Phone and address from DOHMH (by CAMIS) or OSM tags."""
    d = load_raw("dohmh_restaurants")[["camis", "phone"]].drop_duplicates("camis")
    phone_by_camis = dict(zip(d["camis"], d["phone"], strict=True))
    o = pd.read_parquet(PROCESSED / "osm_places.parquet", columns=["osm_type", "osm_id", "tags"])
    o["place_id"] = "osm:" + o["osm_type"] + ":" + o["osm_id"].astype(str)
    tags = dict(zip(o["place_id"], o["tags"], strict=True))
    phones, addrs = [], []
    for r in s.itertuples():
        t = json.loads(tags[r.place_id]) if r.place_id in tags else {}
        ph = phone_by_camis.get(r.camis) if isinstance(r.camis, str) else None
        ph = ph or t.get("phone") or t.get("contact:phone") or ""
        street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
        addr = street or (r.dohmh_address if isinstance(r.dohmh_address, str) else "")
        phones.append(ph)
        addrs.append(addr)
    s = s.copy()
    s["phone"], s["address"] = phones, addrs
    return s


def write_sheet(s: pd.DataFrame) -> pd.DataFrame:
    s = _contact(s)
    sheet = pd.DataFrame(
        {
            "audit_id": s["audit_id"],
            "group": s["group"],
            "reserve_rank": s["reserve_rank"],
            "name": s["name"].fillna("(no name)"),
            "address": s["address"],
            "borough": s["borough"],
            "phone": s["phone"],
            "type": s["fine_class"],
            "map": [
                f"https://www.openstreetmap.org/?mlat={la:.5f}&mlon={lo:.5f}#map=19/{la:.5f}/{lo:.5f}"
                for la, lo in zip(s["lat"], s["lon"], strict=True)
            ],
            "place_id": s["place_id"],
            **{c: "" for c in FILL},
        }
    )
    sheet.to_csv(SHEET, index=False)
    return sheet


def audited_place_ids() -> set[str]:
    return set(pd.read_csv(SHEET)["place_id"])
