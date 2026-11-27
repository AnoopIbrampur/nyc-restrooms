"""Subway entries by station x hour-of-week, aggregated server-side from MTA hourly ridership.

Windows match the hours reference seasons (pre-registration):
  summer: 2026-07-06 .. 2026-08-02
  winter: 2026-01-05 .. 2026-02-01, excluding 2026-01-19 (MLK Day)

Each (station, weekday, hour) value is the mean over the distinct dates in the window
for that weekday (missing station-hours count as 0 entries). Weekday is Monday = 0,
matching the hours masks.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pandas as pd

from restrooms.check import UA, make_session
from restrooms.paths import MANIFEST, RAW, ensure_dirs
from restrooms.sources import by_key

WINDOWS = {
    "summer": (date(2026, 7, 6), date(2026, 8, 2), set()),
    "winter": (date(2026, 1, 5), date(2026, 2, 1), {date(2026, 1, 19)}),
}
PAGE = 50_000


def _query(session, url: str, params: dict) -> pd.DataFrame:
    frames, offset = [], 0
    while True:
        r = session.get(
            url, params={**params, "$limit": PAGE, "$offset": offset}, headers=UA, timeout=300
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        offset += len(rows)
        if len(rows) < PAGE:
            break
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_daily_hourly(season: str, session=None) -> pd.DataFrame:
    """Raw per (station, date, hour) subway entries for one season window."""
    start, end, _ = WINDOWS[season]
    session = session or make_session()
    url = by_key("mta_hourly").resource_url
    where = (
        f"transit_mode = 'subway' AND transit_timestamp between "
        f"'{start.isoformat()}T00:00:00' and '{end.isoformat()}T23:59:59'"
    )
    df = _query(
        session,
        url,
        {
            "$select": "station_complex_id, date_trunc_ymd(transit_timestamp) as d, "
            "date_extract_hh(transit_timestamp) as hh, sum(ridership) as entries",
            "$where": where,
            "$group": "station_complex_id, d, hh",
            "$order": "station_complex_id, d, hh",
        },
    )
    df["date"] = pd.to_datetime(df["d"]).dt.date
    df["hh"] = df["hh"].astype(int)
    df["entries"] = df["entries"].astype(float)
    return df[["station_complex_id", "date", "hh", "entries"]]


def fetch_stations(session=None) -> pd.DataFrame:
    session = session or make_session()
    url = by_key("mta_hourly").resource_url
    df = _query(
        session,
        url,
        {
            "$select": "station_complex_id, station_complex, borough, "
            "avg(latitude) as lat, avg(longitude) as lon",
            "$where": "transit_mode = 'subway' AND transit_timestamp > '2026-01-01T00:00:00'",
            "$group": "station_complex_id, station_complex, borough",
        },
    )
    df["lat"], df["lon"] = df["lat"].astype(float), df["lon"].astype(float)
    # a complex can appear under >1 name/borough spelling; keep one row per id
    return df.drop_duplicates("station_complex_id").reset_index(drop=True)


def hour_of_week_means(daily: pd.DataFrame, season: str) -> pd.DataFrame:
    """(station, date, hh) -> mean entries per (station, weekday, hh), zero-filled."""
    _, _, exclude = WINDOWS[season]
    daily = daily[~daily["date"].isin(exclude)].copy()
    daily["dow"] = pd.to_datetime(daily["date"]).dt.day_of_week  # Monday = 0
    n_dates = daily.groupby("dow")["date"].nunique()
    total = daily.groupby(["station_complex_id", "dow", "hh"])["entries"].sum()
    stations = daily["station_complex_id"].unique()
    full = pd.MultiIndex.from_product(
        [stations, range(7), range(24)], names=["station_complex_id", "dow", "hh"]
    )
    total = total.reindex(full, fill_value=0.0).reset_index()
    total["mean_entries"] = total["entries"] / total["dow"].map(n_dates)
    total["how"] = total["dow"] * 24 + total["hh"]  # hour-of-week index, matches masks
    return total[["station_complex_id", "dow", "hh", "how", "mean_entries"]]


def check_weekday_encoding(how: pd.DataFrame) -> None:
    """Both weekend slots (dow 5, 6) must be well below Tue-Thu at 8am. A one-day shift
    (e.g. reading SoQL's Sunday=0 as Monday=0) puts a weekday into a weekend slot."""
    at8 = how[how["hh"] == 8].groupby("dow")["mean_entries"].sum()
    midweek = at8.loc[[1, 2, 3]].mean()
    for d in (5, 6):
        if not at8.loc[d] < 0.6 * midweek:
            raise AssertionError(
                f"weekday encoding off: dow {d} 8am {at8.loc[d]:.0f} vs Tue-Thu {midweek:.0f}"
            )


def ingest_ridership() -> dict:
    ensure_dirs()
    session = make_session()
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    info = {}
    for season in WINDOWS:
        daily = fetch_daily_hourly(season, session)
        how = hour_of_week_means(daily, season)
        check_weekday_encoding(how)
        how.to_parquet(RAW / f"ridership_{season}.parquet", index=False)
        info[season] = {
            "dates_used": int(daily.loc[~daily["date"].isin(WINDOWS[season][2]), "date"].nunique()),
            "stations": int(how["station_complex_id"].nunique()),
            "weekly_entries": round(float(how["mean_entries"].sum())),
        }
    stations = fetch_stations(session)
    stations.to_parquet(RAW / "subway_stations.parquet", index=False)
    info["station_rows"] = len(stations)
    manifest["mta_hourly"] = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **info,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(info)
    return info
