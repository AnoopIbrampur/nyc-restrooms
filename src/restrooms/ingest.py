"""Download and cache raw sources to data/raw/, and record a manifest of what was fetched.

Socrata tables -> parquet (all columns as strings; typing happens downstream).
Refuge -> parquet (paged by distance from City Hall until empty).
OSM extract -> .pbf file (re-downloaded only if the server copy is newer).
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

from restrooms.check import UA, make_session
from restrooms.paths import MANIFEST, RAW, ensure_dirs
from restrooms.sources import Kind, Source, by_key

PAGE = 50_000

# Column subsets for big tables (None = all columns).
SELECT: dict[str, list[str]] = {
    "dohmh_restaurants": [
        "camis",
        "dba",
        "boro",
        "building",
        "street",
        "zipcode",
        "phone",
        "cuisine_description",
        "inspection_date",
        "latitude",
        "longitude",
        "bin",
        "bbl",
        "nta",
    ],
}

# Sources downloaded in Phase 1 (later-phase heavy tables are fetched when needed).
PHASE1 = (
    "nyc_restrooms",
    "parks_restroom_sites",
    "parks_restroom_inspections",
    "parks_restroom_ratings",
    "parks_restroom_hazards",
    "parks_inspections",
    "parks_sites",
    "refuge",
    "dohmh_restaurants",
    "boroughs",
    "mta_stations",
    "ped_counts",
    "osm_extract",
)

# City Hall; Refuge's by_location search is sorted by distance from here.
REFUGE_CENTER = {"lat": "40.7128", "lng": "-74.0060"}


def _socrata_meta(s: Source, session: requests.Session) -> dict:
    r = session.get(s.metadata_url, headers=UA, timeout=120)
    r.raise_for_status()
    return r.json()


def fetch_socrata(s: Source, session: requests.Session) -> tuple[pd.DataFrame, dict]:
    meta = _socrata_meta(s, session)
    params = {"$limit": str(PAGE), "$order": ":id"}
    if s.key in SELECT:
        params["$select"] = ",".join(SELECT[s.key])
    frames, offset = [], 0
    while True:
        r = session.get(
            s.resource_url, params={**params, "$offset": str(offset)}, headers=UA, timeout=300
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        offset += len(rows)
        if len(rows) < PAGE:
            break
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    df = df[[c for c in df.columns if not c.startswith(":@")]]
    df = df.map(lambda v: json.dumps(v) if isinstance(v, dict | list) else v).astype("string")
    ts = meta.get("rowsUpdatedAt")
    info = {"rows_updated_at": datetime.fromtimestamp(ts, UTC).isoformat() if ts else None}
    return df, info


def fetch_refuge(s: Source, session: requests.Session) -> tuple[pd.DataFrame, dict]:
    rows, page = [], 1
    while True:
        r = session.get(
            s.url,
            params={**REFUGE_CENTER, "per_page": "100", "page": str(page)},
            headers=UA,
            timeout=120,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        page += 1
    df = pd.DataFrame(rows).astype("string")
    return df, {"pages": page - 1}


def fetch_file(s: Source, session: requests.Session, force: bool = False) -> tuple[None, dict]:
    dest = RAW / s.url.rsplit("/", 1)[-1]
    head = session.head(s.url, headers=UA, timeout=60, allow_redirects=True)
    head.raise_for_status()
    remote = head.headers.get("Last-Modified")
    remote_dt = parsedate_to_datetime(remote) if remote else None
    fresh = (
        dest.exists()
        and remote_dt is not None
        and datetime.fromtimestamp(dest.stat().st_mtime, UTC) >= remote_dt
    )
    if not fresh or force:
        tmp = dest.with_suffix(".part")
        with session.get(s.url, headers=UA, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                shutil.copyfileobj(r.raw, f, length=1 << 20)
        tmp.replace(dest)
    return None, {
        "path": str(dest.relative_to(RAW.parent.parent)),
        "remote_last_modified": remote_dt.isoformat() if remote_dt else None,
        "bytes": dest.stat().st_size,
        "downloaded": not fresh or force,
    }


def ingest(keys: Iterable[str] = PHASE1, force: bool = False) -> dict:
    ensure_dirs()
    session = make_session()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for key in keys:
        s = by_key(key)
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        if s.kind is Kind.FILE:
            _, info = fetch_file(s, session, force)
        else:
            df, info = (fetch_refuge if s.key == "refuge" else fetch_socrata)(s, session)
            df.to_parquet(RAW / f"{key}.parquet", index=False)
            info["rows"] = len(df)
        manifest[key] = {"fetched_at": fetched_at, **info}
        print(f"{key:28s} {info}")
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def load_raw(key: str) -> pd.DataFrame:
    return pd.read_parquet(RAW / f"{key}.parquet")
