"""Parks restroom condition overlay (Phase 2, timeboxed).

The restroom inspections' `csnumber` is a 1..3 ordinal *within an inspection*, not the
comfort-station id (`cs_id`) of the restroom sites table, so ratings can't be joined to a
specific restroom. They CAN be joined at the park-property level:

  restroom inspection --inspectionid--> inspection (prop_id, date)

and for properties with exactly ONE comfort station in the sites table, the property's
latest rating can only belong to that station. Official Parks restrooms are placed in a
property by point-in-polygon on the Parks Inspection Program site polygons. Restrooms in
multi-station properties get no rating (left blank, not guessed).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from shapely import STRtree, points
from shapely.geometry import shape

from restrooms.ingest import load_raw


def latest_property_rating() -> pd.DataFrame:
    ri = load_raw("parks_restroom_inspections")
    pi = load_raw("parks_inspections")[["inspection_id", "prop_id", "date"]]
    m = ri.merge(pi, left_on="inspectionid", right_on="inspection_id")
    m["date"] = pd.to_datetime(m["date"])
    # worst of the station ratings within the latest inspection of each property
    latest = m[m["date"] == m.groupby("prop_id")["date"].transform("max")]
    agg = latest.groupby("prop_id").agg(
        condition=("cs_overall_condition", lambda s: "U" if (s == "U").any() else s.iloc[0]),
        inspected=("date", "max"),
        stations_rated=("csnumber", "nunique"),
    )
    return agg.reset_index()


def single_station_props() -> set[str]:
    rs = load_raw("parks_restroom_sites")
    n = rs.groupby("prop_id")["cs_id"].nunique()
    return set(n[n == 1].index)


def property_of(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    sites = load_raw("parks_sites")
    sites = sites[sites["multipolygon"].notna()]
    geoms = [shape(json.loads(g)) for g in sites["multipolygon"]]
    tree = STRtree(geoms)
    pts = points(lon, lat)
    hit_pt, hit_geom = tree.query(pts, predicate="within")
    out = np.full(len(lat), None, dtype=object)
    prop = sites["prop_id"].to_numpy()
    # if a point falls in several polygons (sites nested in properties), keep the first
    for i, j in zip(hit_pt, hit_geom, strict=True):
        if out[i] is None:
            out[i] = prop[j]
    return out


def condition_overlay(places: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    parks = places[places["official_present"] & (places["official_location_type"] == "Park")]
    props = property_of(parks["lat"].to_numpy(), parks["lon"].to_numpy())
    df = pd.DataFrame(
        {
            "place_id": parks["place_id"].to_numpy(),
            "name": parks["name"].to_numpy(),
            "prop_id": props,
        }
    )
    single = single_station_props()
    ratings = latest_property_rating()
    df = df.merge(ratings, on="prop_id", how="left")
    df.loc[~df["prop_id"].isin(single), ["condition", "inspected"]] = None
    stats = {
        "official_park_restrooms": len(df),
        "in_a_property": int(df["prop_id"].notna().sum()),
        "single_station_property": int(df["prop_id"].isin(single).sum()),
        "rated": int(df["condition"].notna().sum()),
        "rating_counts": df["condition"].value_counts().to_dict(),
        "latest_inspection_median": str(pd.to_datetime(df["inspected"]).median())[:10]
        if df["inspected"].notna().any()
        else None,
    }
    return df, stats
