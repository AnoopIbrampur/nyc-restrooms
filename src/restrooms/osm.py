"""Extract NYC points of interest from the Geofabrik New York State .osm.pbf.

Keeps nodes and ways carrying any of KEEP_KEYS (amenity/shop/tourism/leisure or a
toilets* tag). Ways become a point at the mean of their node coordinates. Relations
are skipped and counted: statewide ~4.2k, mostly parking, nature
reserves and park outlines (parks are covered by the official restrooms data).

Output is one row per OSM element inside the five boroughs (land polygons from
NYC's Borough Boundaries dataset).
"""

from __future__ import annotations

import json
from pathlib import Path

import osmium
import pandas as pd
from shapely import contains_xy
from shapely.geometry import shape
from shapely.ops import unary_union

KEEP_KEYS = ("amenity", "shop", "tourism", "leisure", "toilets", "toilets:access")

# Tags promoted to columns (prefix "t_" with ':' -> '_'). Everything is also kept in `tags`.
COLUMNS = (
    "name",
    "brand",
    "operator",
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "toilets",
    "toilets:access",
    "toilets:wheelchair",
    "toilets:fee",
    "changing_table",
    "toilets:changing_table",
    "unisex",
    "wheelchair",
    "access",
    "fee",
    "opening_hours",
    "level",
    "addr:housenumber",
    "addr:street",
    "addr:postcode",
)


def col(tag: str) -> str:
    return "t_" + tag.replace(":", "_")


def nyc_polygon(boroughs: pd.DataFrame):
    """Union of the five borough land polygons from the raw `boroughs` table."""
    geoms = [shape(json.loads(g)) for g in boroughs["the_geom"]]
    return unary_union(geoms)


def extract(pbf: Path, boundary) -> tuple[pd.DataFrame, dict]:
    minx, miny, maxx, maxy = boundary.bounds
    rows: list[dict] = []
    stats = {"relations_skipped": 0, "ways_no_coords": 0, "outside": 0}

    fp = (
        osmium.FileProcessor(str(pbf))
        .with_locations()
        .with_filter(osmium.filter.KeyFilter(*KEEP_KEYS))
    )
    for obj in fp:
        if obj.is_relation():
            stats["relations_skipped"] += 1
            continue
        if obj.is_node():
            if not obj.location.valid():
                continue
            lon, lat, kind = obj.location.lon, obj.location.lat, "node"
        else:  # way
            pts = [(n.lon, n.lat) for n in obj.nodes if n.location.valid()]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if not pts:
                stats["ways_no_coords"] += 1
                continue
            lon = sum(p[0] for p in pts) / len(pts)
            lat = sum(p[1] for p in pts) / len(pts)
            kind = "way"
        if not (minx <= lon <= maxx and miny <= lat <= maxy):
            continue
        tags = {t.k: t.v for t in obj.tags}
        row = {"osm_type": kind, "osm_id": obj.id, "lat": lat, "lon": lon}
        row.update({col(k): tags.get(k) for k in COLUMNS})
        row["tags"] = json.dumps(tags, ensure_ascii=False)
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df, stats
    inside = contains_xy(boundary, df["lon"].to_numpy(), df["lat"].to_numpy())
    stats["outside"] = int((~inside).sum())
    df = df[inside].reset_index(drop=True)
    stats["kept"] = len(df)
    return df, stats


def summary_counts(df: pd.DataFrame) -> dict[str, int]:
    """Counts comparable to the Overpass checks done on 2026-11-26."""
    food = df["t_amenity"].isin(["restaurant", "cafe", "fast_food", "bar", "pub"])
    return {
        "amenity_toilets": int((df["t_amenity"] == "toilets").sum()),
        "toilets_tag_any": int(df["t_toilets"].notna().sum()),
        "toilets_yes": int((df["t_toilets"] == "yes").sum()),
        "toilets_no": int((df["t_toilets"] == "no").sum()),
        "food_places": int(food.sum()),
        "shops": int(df["t_shop"].notna().sum()),
    }


# Overpass counts for the NYC admin relation (175905), taken 2026-11-26. The relation area
# includes water; borough land polygons don't, so expect our counts slightly lower.
OVERPASS_REFERENCE = {
    "amenity_toilets": 796,
    "toilets_tag_any": 1351,
    "toilets_yes": 1070,
    "toilets_no": 248,
    "food_places": 17322,
    "shops": 25942,
}
