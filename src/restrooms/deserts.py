"""Phase 2: walking time to the nearest open restroom, by hour of week, season and scenario.

Implements docs/phase2_prereg.md. Every number in the headline comes from `headline()`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import h3
import numpy as np
import pandas as pd
from shapely.geometry import mapping

from restrooms.hours import HOURS
from restrooms.ingest import load_raw
from restrooms.match import candidates
from restrooms.osm import nyc_polygon
from restrooms.paths import DOCS, PROCESSED, RAW
from restrooms.walk import WalkGraph, nearest_source_distance, walk_minutes

THRESHOLD_MIN = 10.0
HEADLINE_HOURS = (9, 18, 23)
SEASONS = ("summer", "winter")
READINGS = ("A", "B")
HEX_RES = 9
HEX_MAX_SNAP_M = 150.0
DUSK_SUMMER_HOUR = 20  # reading B: "open later seasonally" closes at dusk in summer
NOT_PUBLIC = {"private", "no", "customers"}
CUSTOMER_OK = {"yes", "customers", "permissive", "public"}


# ---------------------------------------------------------------------------
# Restroom sets
# ---------------------------------------------------------------------------
def extend_to_dusk(mask: str) -> str:
    """Reading B: a day open at 15:30 stays open through 19:59."""
    m = list(mask)
    for d in range(7):
        if m[d * 24 + 15] == "1":
            for h in range(16, DUSK_SUMMER_HOUR):
                m[d * 24 + h] = "1"
    return "".join(m)


@dataclass
class RestroomSet:
    name: str
    lat: np.ndarray
    lon: np.ndarray
    masks: dict[tuple[str, str], np.ndarray]  # (season, reading) -> bool [n, 168]


def _mask_matrix(masks: pd.Series, default_open: bool = False) -> np.ndarray:
    out = np.zeros((len(masks), HOURS), dtype=bool)
    for i, m in enumerate(masks):
        if isinstance(m, str):
            out[i] = np.frombuffer(m.encode(), dtype=np.uint8) == ord("1")
        elif default_open:
            out[i] = True
    return out


def public_osm_toilets(p: pd.DataFrame) -> pd.Series:
    return (
        (p["category"] == "amenity=toilets")
        & ~p["official_present"]
        & ~p["osm_access"].isin(NOT_PUBLIC)
        & (p["osm_fee"] != "yes")
    )


def restroom_sets(p: pd.DataFrame) -> dict[str, RestroomSet]:
    """primary / sensitivity / purchase, per the pre-registration."""
    off = p["official_present"]
    ext = p["hours_flags"].fillna("").str.contains("season_extension_unknown")
    osm_t = public_osm_toilets(p)
    osm_known = osm_t & (p["hours_source"] == "osm")

    def build(rows: pd.Series, default_open: pd.Series | None, name: str) -> RestroomSet:
        sub = p[rows]
        d_open = default_open[rows] if default_open is not None else pd.Series(False, sub.index)
        masks = {}
        for season in SEASONS:
            col = sub[f"hours_{season}"]
            base = _mask_matrix(col)
            # unknown hours -> always open, only where this set says so
            unknown = col.isna().to_numpy() & d_open.to_numpy()
            base[unknown] = True
            for reading in READINGS:
                m = base.copy()
                if reading == "B" and season == "summer":
                    e = ext[rows].to_numpy() & col.notna().to_numpy()
                    for i in np.flatnonzero(e):
                        m[i] = _mask_matrix(pd.Series([extend_to_dusk(col.iloc[i])]))[0]
                masks[(season, reading)] = m
        return RestroomSet(name, sub["lat"].to_numpy(), sub["lon"].to_numpy(), masks)

    primary_rows = (off & p["hours_summer"].notna()) | osm_known
    sens_rows = off | osm_t
    sens_default = (off & p["hours_summer"].isna()) | (osm_t & ~osm_known)

    cust = (
        (
            p["osm_toilets"].isin({"yes", "customers"})
            | p["osm_toilets_access"].isin(CUSTOMER_OK)
            | p["refuge_present"]
        )
        & ~off
        & ~osm_t
        & p["hours_summer"].notna()
    )
    purchase_rows = primary_rows | cust

    # EXPLORATORY (not pre-registered): the sensitivity bound, minus unknown-hour OSM
    # toilets within 150 m of an official restroom (mostly the same park comfort stations,
    # which follow park hours rather than being open 24/7).
    near = near_official(p, osm_t & ~osm_known, DUPLICATE_M)
    explo_rows = sens_rows & ~near

    return {
        "primary": build(primary_rows, None, "primary"),
        "sensitivity": build(sens_rows, sens_default, "sensitivity"),
        "exploratory_sensitivity_no_near_official": build(explo_rows, sens_default, "exploratory"),
        "purchase": build(purchase_rows, None, "purchase"),
    }


DUPLICATE_M = 150.0


def near_official(p: pd.DataFrame, rows: pd.Series, radius_m: float) -> pd.Series:
    """Rows (subset mask) lying within radius_m of any official restroom."""
    sub = p[rows].reset_index()
    off = p[p["official_present"]].reset_index(drop=True)
    sub["norm_name"], off["norm_name"] = "", ""
    c = candidates(sub, off, radius_m)
    hit = pd.Series(False, index=p.index)
    hit.loc[sub.loc[np.unique(c.left), "index"].to_numpy()] = True
    return hit


# ---------------------------------------------------------------------------
# Walk times
# ---------------------------------------------------------------------------
def minutes_by_hour(
    g: WalkGraph, rs: RestroomSet, season: str, reading: str, targets: dict[str, tuple]
) -> dict[str, np.ndarray]:
    """For each target group -> minutes array [n_targets, 168]. One Dijkstra per unique
    set of open restrooms."""
    src_node, src_snap = g.snap(rs.lat, rs.lon)
    mask = rs.masks[(season, reading)]
    out = {k: np.full((len(v[0]), HOURS), np.inf) for k, v in targets.items()}
    cache: dict[bytes, np.ndarray] = {}
    for h in range(HOURS):
        key = np.packbits(mask[:, h]).tobytes()
        if key not in cache:
            open_ = mask[:, h]
            cache[key] = nearest_source_distance(g, src_node[open_], src_snap[open_])
        dist = cache[key]
        for k, (node, snap) in targets.items():
            out[k][:, h] = walk_minutes(dist, node, snap)
    return out


def nyc_hexes(boroughs: pd.DataFrame) -> pd.DataFrame:
    poly = nyc_polygon(boroughs)
    cells = h3.geo_to_cells(mapping(poly), HEX_RES)
    centers = [h3.cell_to_latlng(c) for c in cells]
    return pd.DataFrame(
        {"h3": list(cells), "lat": [c[0] for c in centers], "lon": [c[1] for c in centers]}
    )


# ---------------------------------------------------------------------------
# Metric
# ---------------------------------------------------------------------------
def share_over(minutes: np.ndarray, entries: np.ndarray, hour: int, thr: float) -> float:
    """Weekday (Mon-Fri) share of entries at the given hour where minutes > thr.
    minutes, entries: [n_stations, 168]."""
    cols = [d * 24 + hour for d in range(5)]
    e = entries[:, cols]
    over = minutes[:, cols] > thr
    return float((e * over).sum() / e.sum())


def entries_matrix(stations: pd.DataFrame, season: str) -> np.ndarray:
    r = pd.read_parquet(RAW / f"ridership_{season}.parquet")
    piv = r.pivot_table(
        index="station_complex_id", columns="how", values="mean_entries", fill_value=0.0
    )
    piv = piv.reindex(index=stations["station_complex_id"], columns=range(HOURS), fill_value=0.0)
    return piv.to_numpy()


def run() -> dict:
    p = pd.read_parquet(PROCESSED / "places.parquet")
    g = WalkGraph.load(PROCESSED / "walk_graph.npz")
    stations = pd.read_parquet(RAW / "subway_stations.parquet")
    hexes = nyc_hexes(load_raw("boroughs"))

    st_node, st_snap = g.snap(stations["lat"].to_numpy(), stations["lon"].to_numpy())
    hx_node, hx_snap = g.snap(hexes["lat"].to_numpy(), hexes["lon"].to_numpy())
    hexes["snap_m"] = hx_snap
    hexes["no_network"] = hx_snap > HEX_MAX_SNAP_M
    targets = {"stations": (st_node, st_snap), "hexes": (hx_node, hx_snap)}

    sets = restroom_sets(p)
    entries = {s: entries_matrix(stations, s) for s in SEASONS}

    results: dict = {
        "restroom_counts": {k: int(len(v.lat)) for k, v in sets.items()},
        "stations": len(stations),
        "station_snap_m_max": round(float(st_snap.max()), 1),
        "hexes": len(hexes),
        "hexes_no_network": int(hexes["no_network"].sum()),
        "H": {},
        "sensitivity": {},
        "exploratory_sensitivity_no_near_official": {},
        "purchase": {},
        "threshold_curve": {},
        "hour_profile": {},
    }
    station_minutes: dict = {}
    for set_name, rs in sets.items():
        for season in SEASONS:
            for reading in READINGS:
                m = minutes_by_hour(g, rs, season, reading, targets)
                station_minutes[(set_name, season, reading)] = m["stations"]
                if set_name == "primary":
                    np.save(
                        PROCESSED / f"hex_minutes_{season}_{reading}.npy",
                        m["hexes"].astype(np.float32),
                    )
                e = entries[season]
                key = f"{season}_{reading}"
                cells = {
                    f"{h:02d}:00": round(share_over(m["stations"], e, h, THRESHOLD_MIN), 4)
                    for h in HEADLINE_HOURS
                }
                target = {"primary": "H"}.get(set_name, set_name)
                results[target][key] = cells
                if set_name == "primary":
                    results["threshold_curve"][key] = {
                        str(t): {
                            f"{h:02d}:00": round(share_over(m["stations"], e, h, t), 4)
                            for h in HEADLINE_HOURS
                        }
                        for t in (5, 10, 15)
                    }
                    results["hour_profile"][key] = [
                        round(share_over(m["stations"], e, h, THRESHOLD_MIN), 4) for h in range(24)
                    ]

    # worst stations: summer, reading A, primary
    m = station_minutes[("primary", "summer", "A")]
    e = entries["summer"]
    wk = list(range(5 * 24))
    stranded = (e[:, wk] * (m[:, wk] > THRESHOLD_MIN)).sum(axis=1) / 5
    daily = e[:, wk].sum(axis=1) / 5
    worst = stations.assign(
        stranded_entries_per_weekday=stranded.round(0),
        weekday_entries=daily.round(0),
        share_stranded=np.where(daily > 0, stranded / np.maximum(daily, 1), 0).round(3),
        minutes_9am=m[:, 9].round(1),
        minutes_6pm=m[:, 18].round(1),
        minutes_11pm=m[:, 23].round(1),
    ).sort_values("stranded_entries_per_weekday", ascending=False)
    worst.to_csv(DOCS / "phase2_station_table.csv", index=False)
    results["worst_20"] = worst.head(20)[
        [
            "station_complex",
            "borough",
            "weekday_entries",
            "stranded_entries_per_weekday",
            "share_stranded",
            "minutes_9am",
            "minutes_6pm",
            "minutes_11pm",
        ]
    ].to_dict(orient="records")

    # borough breakdown of H (excluding Staten Island)
    results["borough"] = {}
    for season in SEASONS:
        for reading in READINGS:
            mm = station_minutes[("primary", season, reading)]
            ee = entries[season]
            out = {}
            for b in ("Manhattan", "Brooklyn", "Queens", "Bronx"):
                idx = (stations["borough"] == b).to_numpy()
                out[b] = {
                    f"{h:02d}:00": round(share_over(mm[idx], ee[idx], h, THRESHOLD_MIN), 4)
                    for h in HEADLINE_HOURS
                }
            results["borough"][f"{season}_{reading}"] = out

    # stated expectation: 23:00 exceeds 09:00 by >= 20 pp in both seasons
    results["expectation_23_minus_09_pp"] = {
        k: round((v["23:00"] - v["09:00"]) * 100, 1) for k, v in results["H"].items()
    }
    hexes.to_parquet(PROCESSED / "hexes.parquet", index=False)
    (DOCS / "phase2_results.json").write_text(json.dumps(results, indent=2, default=float) + "\n")
    print(
        json.dumps(
            {
                k: results[k]
                for k in (
                    "restroom_counts",
                    "H",
                    "sensitivity",
                    "purchase",
                    "expectation_23_minus_09_pp",
                )
            },
            indent=1,
        )
    )
    return results
