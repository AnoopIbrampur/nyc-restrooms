"""Public app data (docs/data/restrooms.json), shared by the worker page and the app.

Built from two inputs so the nightly refresh is cheap:
- the NYC Public Restrooms table (small; re-downloaded nightly), and
- a committed snapshot of OpenStreetMap public toilets (data_snapshots/osm_toilets.json),
  regenerated only when the OSM extract is rebuilt (`make_snapshot`).

Restroom ids are stable: official restrooms use a hash of name + location (the city's
table has no id column, and row numbers shift); OSM toilets use their OSM id.

Filter fields use "yes" / "limited" / "no" / "unknown"; "unknown" is never treated as
"no". Hours masks use reading A (the conservative one). Unknown hours -> null.

A validation gate runs before anything is written; it raises instead of publishing
bad data. The pre-registered analysis outputs are never touched here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pandas as pd

from restrooms import hours
from restrooms.build import apply_official_status
from restrooms.paths import DOCS, PROCESSED, ROOT

SNAPSHOT = ROOT / "data_snapshots" / "osm_toilets.json"
OUT = DOCS / "data"
BBOX = (-74.27, 40.49, -73.68, 40.92)
NOT_PUBLIC = {"private", "no", "customers"}


class ValidationError(RuntimeError):
    pass


def stable_id(name: str, lat: float, lon: float) -> str:
    key = f"{name.strip().lower()}|{lat:.5f}|{lon:.5f}"
    return "nyc:" + hashlib.sha1(key.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# OSM snapshot
# ---------------------------------------------------------------------------
def make_snapshot() -> int:
    """From the full build: public OSM toilets not matched to an official restroom."""
    from restrooms.deserts import public_osm_toilets

    p = pd.read_parquet(PROCESSED / "places.parquet")
    t = p[public_osm_toilets(p)]
    o = pd.read_parquet(PROCESSED / "osm_places.parquet", columns=["osm_type", "osm_id", "tags"])
    o["place_id"] = "osm:" + o["osm_type"] + ":" + o["osm_id"].astype(str)
    tags = dict(zip(o["place_id"], o["tags"], strict=True))
    rows = []
    for r in t.itertuples():
        g = json.loads(tags[r.place_id])
        rows.append(
            {
                "id": r.place_id,
                "name": g.get("name"),
                "lat": round(float(r.lat), 6),
                "lon": round(float(r.lon), 6),
                "opening_hours": g.get("opening_hours"),
                "wheelchair": g.get("wheelchair") or g.get("toilets:wheelchair"),
                "changing_table": g.get("changing_table") or g.get("toilets:changing_table"),
                "unisex": g.get("unisex") or g.get("toilets:unisex"),
                "access": g.get("access"),
                "fee": g.get("fee"),
            }
        )
    SNAPSHOT.parent.mkdir(exist_ok=True)
    SNAPSHOT.write_text(json.dumps(rows, indent=0, sort_keys=True) + "\n")
    return len(rows)


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------
def _official_access(v) -> str:
    v = v if isinstance(v, str) else ""
    if v.startswith("Fully"):
        return "yes"
    if v.startswith(("Partially", "Limited")):
        return "limited"
    if v.startswith("Not"):
        return "no"
    return "unknown"


def _official_changing(v) -> str:
    v = (v if isinstance(v, str) else "").strip('"')
    if v.startswith("Yes"):
        return "yes"
    if v == "No":
        return "no"
    return "unknown"


def _official_gender_neutral(v) -> str:
    v = v if isinstance(v, str) else ""
    if "All Gender" in v:
        return "yes"
    if "W/M" in v:
        return "no"
    return "unknown"


def _osm_yesno(v, limited: bool = False) -> str:
    if v in ("yes", "designated"):
        return "yes"
    if limited and v == "limited":
        return "limited"
    if v == "no":
        return "no"
    return "unknown"


def _mask(m) -> str | None:
    return m if isinstance(m, str) else None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build(official_raw: pd.DataFrame, snapshot: list[dict]) -> list[dict]:
    out = []
    for r in official_raw.itertuples():
        lat, lon = (
            pd.to_numeric(r.latitude, errors="coerce"),
            pd.to_numeric(r.longitude, errors="coerce"),
        )
        if pd.isna(lat) or pd.isna(lon) or not isinstance(r.facility_name, str):
            continue
        status = getattr(r, "status", None)
        season = getattr(r, "open", None)
        if status != "Operational" or season == "Future":
            continue  # closed per the city's own data: not shown
        text = getattr(r, "hours_of_operation", None)
        h = hours.parse_nyc(text)
        s, w, flags = apply_official_status(h.summer, h.winter, set(h.flags), status, season)
        out.append(
            {
                "id": stable_id(r.facility_name, float(lat), float(lon)),
                "n": r.facility_name,
                "t": r.location_type if isinstance(r.location_type, str) else "Public restroom",
                "src": "nyc",
                "la": round(float(lat), 5),
                "lo": round(float(lon), 5),
                "h": text if isinstance(text, str) else "",
                "s": _mask(s),
                "w": _mask(w),
                "acc": _official_access(getattr(r, "accessibility", None)),
                "chg": _official_changing(getattr(r, "changing_stations", None)),
                "gn": _official_gender_neutral(getattr(r, "restroom_type", None)),
                "seasonal": season == "Seasonal",
                "later": "season_extension_unknown" in flags,
            }
        )
    # The city's table contains exact duplicate rows (same name, location, hours): keep one.
    seen: set[str] = set()
    deduped = []
    for row in out:
        if row["id"] not in seen:
            seen.add(row["id"])
            deduped.append(row)
    build.duplicates_collapsed = len(out) - len(deduped)
    out = deduped
    for t in snapshot:
        if t.get("access") in NOT_PUBLIC or t.get("fee") == "yes":
            continue
        h = hours.parse_osm(t.get("opening_hours"))
        out.append(
            {
                "id": t["id"],
                "n": t.get("name") or "Public toilet",
                "t": "Public toilet (OpenStreetMap)",
                "src": "osm",
                "la": round(float(t["lat"]), 5),
                "lo": round(float(t["lon"]), 5),
                "h": t.get("opening_hours") or "",
                "s": _mask(h.summer),
                "w": _mask(h.winter),
                "acc": _osm_yesno(t.get("wheelchair"), limited=True),
                "chg": _osm_yesno(t.get("changing_table")),
                "gn": _osm_yesno(t.get("unisex")),
                "seasonal": False,
                "later": False,
            }
        )
    return out


def validate(rows: list[dict]) -> dict:
    """Fail loudly instead of publishing bad data."""
    nyc = [r for r in rows if r["src"] == "nyc"]
    osm = [r for r in rows if r["src"] == "osm"]
    if not 800 <= len(nyc) <= 1500:
        raise ValidationError(f"official restrooms out of range: {len(nyc)}")
    if not 300 <= len(osm) <= 1500:
        raise ValidationError(f"OSM toilets out of range: {len(osm)}")
    with_hours = sum(r["s"] is not None for r in nyc) / len(nyc)
    if with_hours < 0.85:
        raise ValidationError(f"official hours parse rate too low: {with_hours:.2f}")
    bad = [
        r["id"]
        for r in rows
        if not (BBOX[0] <= r["lo"] <= BBOX[2] and BBOX[1] <= r["la"] <= BBOX[3])
    ]
    if bad:
        raise ValidationError(f"{len(bad)} restrooms outside NYC, e.g. {bad[:3]}")
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValidationError("duplicate restroom ids")
    for r in rows:
        for m in ("s", "w"):
            if r[m] is not None and (len(r[m]) != hours.HOURS or set(r[m]) - {"0", "1"}):
                raise ValidationError(f"bad mask on {r['id']}")
    return {
        "official_duplicates_collapsed": getattr(build, "duplicates_collapsed", 0),
        "official": len(nyc),
        "osm": len(osm),
        "official_with_hours": round(with_hours, 3),
        "osm_with_hours": round(sum(r["s"] is not None for r in osm) / len(osm), 3),
    }


def write(rows: list[dict], stats: dict, source_updated: str | None) -> bool:
    """Write only when the restroom data changed (so quiet nights make no commit)."""
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(rows, separators=(",", ":"), sort_keys=True)
    target = OUT / "restrooms.json"
    if target.exists() and target.read_text() == body:
        return False
    target.write_text(body)
    meta = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "nyc_restrooms_updated": source_updated,
        "hours_reading": 'A ("open later seasonally" closes at 4 pm)',
        **stats,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return True


def fetch_official() -> tuple[pd.DataFrame, str | None]:
    """Fresh copy of the city's table. Does not touch the analysis data manifest."""
    from restrooms.check import make_session
    from restrooms.ingest import fetch_socrata
    from restrooms.sources import by_key

    df, info = fetch_socrata(by_key("nyc_restrooms"), make_session())
    return df, info.get("rows_updated_at")


def refresh(fetch: bool = True) -> dict:
    from restrooms.ingest import load_raw

    if fetch:
        raw, updated = fetch_official()
    else:
        raw = load_raw("nyc_restrooms")
        manifest = json.loads((DOCS / "data_manifest.json").read_text())
        updated = manifest.get("nyc_restrooms", {}).get("rows_updated_at")
    snap = json.loads(SNAPSHOT.read_text())
    rows = build(raw, snap)
    stats = validate(rows)
    stats["changed"] = write(rows, stats, updated)
    print(stats)
    return stats
