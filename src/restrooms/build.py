"""Phase 1 build: raw sources -> data/processed/places.parquet + docs/phase1_report.md.

Labels stay per source (osm_*, official_*, refuge_*); nothing is merged into a single
"access" value, so Phase 3 can tell where each label came from. Delivery-worker
coverage is its own boolean (`likely_covered_pickup`), never an access tier.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from shapely import contains_xy
from shapely.geometry import shape

from restrooms import hours, match
from restrooms.ingest import load_raw
from restrooms.osm import OVERPASS_REFERENCE, extract, nyc_polygon, summary_counts
from restrooms.paths import DOCS, PROCESSED, RAW, ensure_dirs

OSM_PBF = RAW / "new-york-latest.osm.pbf"
AUDIT_SEED = 20261127  # round 2 (round 1 used 20261126 and drove the rule fixes)

# Matching rules (documented in the report)
OFFICIAL_RADIUS, OFFICIAL_TOILET_M, OFFICIAL_SIM = 100.0, 60.0, 85.0
DOHMH_RADIUS, DOHMH_SIM = 75.0, 85.0
REFUGE_RADIUS, REFUGE_SIM = 75.0, 80.0


# ---------------------------------------------------------------------------
# Clean each source
# ---------------------------------------------------------------------------
def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def apply_official_status(summer, winter, flags: set, status, season):
    """The official dataset's status/season fields override hours from any source."""
    if status != "Operational":
        return hours.CLOSED, hours.CLOSED, flags | {"not_operational"}
    if season == "Future":
        return hours.CLOSED, hours.CLOSED, flags | {"future"}
    if season == "Seasonal":
        return summer, hours.CLOSED, flags | {"seasonal_closed_winter"}
    return summer, winter, flags


def clean_official(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "official_id": [f"nyc:{i}" for i in range(len(raw))],
            "name": raw["facility_name"],
            "lat": _num(raw["latitude"]),
            "lon": _num(raw["longitude"]),
            "official_location_type": raw["location_type"],
            "official_operator": raw["operator"],
            "official_status": raw["status"],
            "official_open": raw.get("open"),
            "official_accessibility": raw.get("accessibility"),
            "official_changing_stations": raw.get("changing_stations"),
            "official_restroom_type": raw.get("restroom_type"),
            "hours_text": raw.get("hours_of_operation"),
        }
    )
    parsed = [hours.parse_nyc(t) for t in df["hours_text"]]
    summer, winter, conf, flags = [], [], [], []
    for p, status, season in zip(parsed, df["official_status"], df["official_open"], strict=True):
        s, w, f = apply_official_status(p.summer, p.winter, set(p.flags), status, season)
        summer.append(s)
        winter.append(w)
        conf.append(p.confidence)
        flags.append(",".join(sorted(f)))
    df["hours_summer"], df["hours_winter"] = summer, winter
    df["hours_confidence"], df["hours_flags"] = conf, flags
    return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def clean_dohmh(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = raw.copy()
    df["inspection_date"] = pd.to_datetime(df["inspection_date"], errors="coerce")
    df = df.sort_values("inspection_date").groupby("camis", as_index=False).tail(1)
    df["lat"], df["lon"] = _num(df["latitude"]), _num(df["longitude"])
    no_coords = df["lat"].isna() | (df["lat"] == 0) | df["lon"].isna() | (df["lon"] == 0)
    stats = {"establishments": len(df), "no_coords": int(no_coords.sum())}
    df = df[~no_coords]
    out = pd.DataFrame(
        {
            "camis": df["camis"].to_numpy(),
            "name": df["dba"].to_numpy(),
            "lat": df["lat"].to_numpy(),
            "lon": df["lon"].to_numpy(),
            "dohmh_address": (df["building"].fillna("") + " " + df["street"].fillna(""))
            .str.strip()
            .to_numpy(),
            "house_no": df["building"].map(match.house_no).to_numpy(),
            "dohmh_cuisine": df["cuisine_description"].to_numpy(),
            "dohmh_last_inspection": df["inspection_date"].dt.date.astype("string").to_numpy(),
            "dohmh_never_inspected": (df["inspection_date"].dt.year == 1900).to_numpy(),
        }
    )
    stats["never_inspected"] = int(out["dohmh_never_inspected"].sum())
    return out.reset_index(drop=True), stats


def refuge_spam(raw: pd.DataFrame) -> pd.Series:
    """2015 spam wave: personal first names with random-letter 'street' values."""
    street = raw["street"].fillna("")
    return street.str.fullmatch(r"[A-Za-z]{8,}") & street.str.contains(r"[a-z][A-Z]")


def clean_refuge(raw: pd.DataFrame, boundary) -> tuple[pd.DataFrame, dict]:
    spam = refuge_spam(raw)
    df = raw[~spam].copy()
    df["lat"], df["lon"] = _num(df["latitude"]), _num(df["longitude"])
    df = df.dropna(subset=["lat", "lon"])
    inside = contains_xy(boundary, df["lon"].to_numpy(), df["lat"].to_numpy())
    stats = {"fetched": len(raw), "spam": int(spam.sum()), "outside_nyc": int((~inside).sum())}
    df = df[inside]
    out = pd.DataFrame(
        {
            "refuge_id": df["id"].to_numpy(),
            "name": df["name"].to_numpy(),
            "lat": df["lat"].to_numpy(),
            "lon": df["lon"].to_numpy(),
            "refuge_street": df["street"].to_numpy(),
            "house_no": df["street"].map(match.house_no).to_numpy(),
            "refuge_accessible": df["accessible"].eq("True").to_numpy(),
            "refuge_unisex": df["unisex"].eq("True").to_numpy(),
            "refuge_changing_table": df["changing_table"].eq("True").to_numpy(),
            "refuge_updated_at": df["updated_at"].str[:10].to_numpy(),
        }
    )
    stats["kept"] = len(out)
    return out.reset_index(drop=True), stats


def osm_places(boundary) -> tuple[pd.DataFrame, dict]:
    cache = PROCESSED / "osm_places.parquet"
    if cache.exists() and cache.stat().st_mtime >= OSM_PBF.stat().st_mtime:
        df = pd.read_parquet(cache)
        stats = json.loads((PROCESSED / "osm_places.stats.json").read_text())
    else:
        df, stats = extract(OSM_PBF, boundary)
        df.to_parquet(cache, index=False)
        (PROCESSED / "osm_places.stats.json").write_text(json.dumps(stats))
    df = df.copy()
    df["category"] = np.select(
        [
            df["t_amenity"].notna(),
            df["t_shop"].notna(),
            df["t_tourism"].notna(),
            df["t_leisure"].notna(),
        ],
        [
            "amenity=" + df["t_amenity"].astype(str),
            "shop=" + df["t_shop"].astype(str),
            "tourism=" + df["t_tourism"].astype(str),
            "leisure=" + df["t_leisure"].astype(str),
        ],
        default="other",
    )
    df["place_id"] = "osm:" + df["osm_type"] + ":" + df["osm_id"].astype(str)
    stats["counts_before_venue_filter"] = summary_counts(df)
    venue = is_venue(df)
    stats["non_venue_dropped"] = int((~venue).sum())
    return df[venue].reset_index(drop=True), stats


# OSM features that are not places a person walks into to use a restroom: street
# furniture, parking, private pools/gardens, schools. Anything with a toilets* tag is
# always kept, as are toilets themselves.
NON_VENUE = {
    "t_amenity": {
        "parking_space", "bench", "bicycle_parking", "parking", "waste_basket",
        "bicycle_rental", "post_box", "drinking_water", "parking_entrance",
        "vending_machine", "recycling", "shelter", "fountain", "atm", "letter_box",
        "loading_dock", "waste_disposal", "public_bookcase", "lounger", "telephone",
        "charging_station", "clock", "motorcycle_parking", "grit_bin", "bbq", "give_box",
        "compressed_air", "ticket_validator", "water_point", "school", "kindergarten",
        "prep_school", "childcare", "fire_station", "police", "car_wash",
    },
    "t_leisure": {
        "swimming_pool", "garden", "pitch", "picnic_table", "outdoor_seating", "bleachers",
        "track", "fitness_station", "schoolyard", "slipway", "hammock", "firepit",
        "fishing", "hot_tub", "bandstand", "bird_hide", "parklet", "indoor_seating",
        "outside_seating_area", "paddling_pool", "no",
    },
    "t_tourism": {
        "information", "artwork", "viewpoint", "picnic_site", "camp_pitch", "apartment",
        "chalet",
    },
}  # fmt: skip
PUBLIC_ACCESS = {"yes", "public", "customers", "permissive"}


def is_venue(df: pd.DataFrame) -> pd.Series:
    keep = df["t_toilets"].notna() | df["t_toilets_access"].notna()
    keep |= df["t_amenity"] == "toilets"
    # a feature is a non-venue only if its *primary* tag is in the list and it has no
    # other venue-type tag (e.g. a shop that also carries amenity=atm stays)
    primary = df["category"].str.split("=", n=1)
    key = "t_" + primary.str[0]
    val = primary.str[1]
    drop = pd.Series(False, index=df.index)
    for k, vals in NON_VENUE.items():
        drop |= (key == k) & val.isin(vals)
    # pools/gardens explicitly open to the public are venues
    drop &= ~(
        df["t_leisure"].isin({"swimming_pool", "garden"}) & df["t_access"].isin(PUBLIC_ACCESS)
    )
    return keep | ~drop


# ---------------------------------------------------------------------------
# Linking
# ---------------------------------------------------------------------------
def _link(left, right, radius, make_rule):
    """make_rule(left, right) -> rule(dist_m, sim, i, j); frames are re-indexed first."""
    left = left.assign(norm_name=left["name"].map(match.norm_name)).reset_index(drop=True)
    right = right.assign(norm_name=right["name"].map(match.norm_name)).reset_index(drop=True)
    c = match.candidates(left, right, radius)
    m = match.assign(c, make_rule(left, right), radius)
    return left, right, c, m


PARKLIKE = {"park", "playground", "garden", "recreation_ground", "nature_reserve", "common"}


def official_rule(left, right):
    """Official restroom <-> OSM.

    - unnamed OSM toilets: distance only (<= 60 m)
    - official libraries: only OSM libraries; any name within 40 m (OSM often says just
      "Brooklyn Public Library"), else name sim >= 85
    - official parks: OSM park-like features with name sim >= 70 within 60 m, else >= 85
    - anything else: name sim >= 85 and the OSM feature must not be a library
    """
    ltype = left["official_location_type"].fillna("").to_numpy()
    toilet = (right["t_amenity"] == "toilets").to_numpy()
    library = (right["t_amenity"] == "library").to_numpy()
    parklike = right["t_leisure"].isin(PARKLIKE).to_numpy()

    def rule(d, s, i, j):
        if toilet[j]:
            return d <= OFFICIAL_TOILET_M
        if ltype[i] == "Library":
            return library[j] and (d <= 40 or s >= OFFICIAL_SIM)
        if library[j]:
            return False
        if ltype[i] == "Park" and parklike[j]:
            return (s >= 70 and d <= 60) or s >= OFFICIAL_SIM
        return s >= OFFICIAL_SIM

    return rule


def business_rule(min_sim):
    """Name sim >= min_sim, or same house number with name sim >= 65."""

    def make(left, right):
        lh = left["house_no"].fillna("").to_numpy() if "house_no" in left else None
        rh = right["house_no"].fillna("").to_numpy() if "house_no" in right else None

        def rule(d, s, i, j):
            if s >= min_sim:
                return True
            if lh is None or rh is None:
                return False
            return bool(lh[i]) and lh[i] == rh[j] and s >= 65

        return rule

    return make


def _audit_rows(link, left, right, c, m, lcols, rcols, n_match=40, n_miss=20):
    rng = np.random.default_rng(AUDIT_SEED)
    rows = []
    take = m.iloc[rng.permutation(len(m))[:n_match]] if len(m) else m
    for _, r in take.iterrows():
        rows.append(("match", r["left"], r["right"], r["dist_m"], r["sim"]))
    for _, r in match.near_misses(c, m, n_miss, AUDIT_SEED).iterrows():
        rows.append(("near_miss", r["left"], r["right"], r["dist_m"], r["sim"]))
    out = []
    for kind, i, j, d, s in rows:
        li, rj = left.iloc[int(i)], right.iloc[int(j)]
        out.append(
            {
                "link": link,
                "kind": kind,
                "left": " | ".join(str(li.get(k, "")) for k in lcols),
                "right": " | ".join(str(rj.get(k, "")) for k in rcols),
                "dist_m": round(float(d), 1),
                "name_sim": round(float(s), 1),
                "verdict": "",
            }
        )
    return out


def build() -> dict:
    ensure_dirs()
    boroughs = load_raw("boroughs")
    boundary = nyc_polygon(boroughs)
    report: dict = {"built_at": datetime.now(UTC).isoformat(timespec="seconds")}

    official = clean_official(load_raw("nyc_restrooms"))
    dohmh, report["dohmh"] = clean_dohmh(load_raw("dohmh_restaurants"))
    refuge, report["refuge"] = clean_refuge(load_raw("refuge"), boundary)
    osm, report["osm_extract"] = osm_places(boundary)
    report["osm_counts"] = report["osm_extract"].pop("counts_before_venue_filter")
    report["osm_reference"] = OVERPASS_REFERENCE

    audit: list[dict] = []

    # A. official restrooms <-> OSM (unnamed toilets by distance; named features by name)
    osm_a = osm[(osm["t_amenity"] == "toilets") | osm["t_name"].notna()].rename(
        columns={"t_name": "name"}
    )
    la, ra, ca, ma = _link(official, osm_a, OFFICIAL_RADIUS, official_rule)
    audit += _audit_rows(
        "official-osm", la, ra, ca, ma, ["name", "official_location_type"], ["name", "category"]
    )
    off_to_osm = {
        la.iloc[r.left]["official_id"]: ra.iloc[r.right]["place_id"] for r in ma.itertuples()
    }

    # B. DOHMH restaurants <-> named OSM places
    osm_b = osm[osm["t_name"].notna()].rename(columns={"t_name": "name"})
    osm_b = osm_b.assign(house_no=osm_b["t_addr_housenumber"].map(match.house_no))
    lb, rb, cb, mb = _link(dohmh, osm_b, DOHMH_RADIUS, business_rule(DOHMH_SIM))
    audit += _audit_rows(
        "dohmh-osm",
        lb,
        rb,
        cb,
        mb,
        ["name", "dohmh_address"],
        ["name", "category", "t_addr_housenumber", "t_addr_street"],
    )
    dohmh_to_osm = {lb.iloc[r.left]["camis"]: rb.iloc[r.right]["place_id"] for r in mb.itertuples()}

    # C. Refuge <-> named OSM places, then leftovers <-> unmatched DOHMH
    lc, rc, cc, mc = _link(refuge, osm_b, REFUGE_RADIUS, business_rule(REFUGE_SIM))
    audit += _audit_rows(
        "refuge-osm",
        lc,
        rc,
        cc,
        mc,
        ["name", "refuge_street"],
        ["name", "category", "t_addr_housenumber", "t_addr_street"],
    )
    refuge_to = {
        lc.iloc[r.left]["refuge_id"]: rc.iloc[r.right]["place_id"] for r in mc.itertuples()
    }
    ref_left = refuge[~refuge["refuge_id"].isin(refuge_to)]
    dohmh_left = dohmh[~dohmh["camis"].isin(dohmh_to_osm)]
    ld, rd, cd, md = _link(ref_left, dohmh_left, REFUGE_RADIUS, business_rule(REFUGE_SIM))
    refuge_to.update(
        {
            ld.iloc[r.left]["refuge_id"]: "dohmh:" + rd.iloc[r.right]["camis"]
            for r in md.itertuples()
        }
    )

    report["links"] = {
        "official_osm": len(ma),
        "dohmh_osm": len(mb),
        "refuge_osm": len(mc),
        "refuge_dohmh": len(md),
    }

    # ------------------------------------------------------------------ assemble
    places = osm.rename(columns={"t_name": "name"})[
        ["place_id", "name", "lat", "lon", "category", "osm_type", "osm_id"]
    ].copy()
    for src, dst in [
        ("t_toilets", "osm_toilets"),
        ("t_toilets_access", "osm_toilets_access"),
        ("t_toilets_wheelchair", "osm_toilets_wheelchair"),
        ("t_changing_table", "osm_changing_table"),
        ("t_unisex", "osm_unisex"),
        ("t_access", "osm_access"),
        ("t_fee", "osm_fee"),
        ("t_brand", "osm_brand"),
        ("t_opening_hours", "osm_opening_hours"),
    ]:
        places[dst] = osm[src].to_numpy()

    def attach(base: pd.DataFrame, extra: pd.DataFrame, key: str, mapping: dict, prefix_id: str):
        """Merge matched rows onto existing places; append unmatched as new places."""
        extra = extra.drop(columns=["house_no"], errors="ignore").copy()  # link-only helper
        extra["place_id"] = extra[key].map(mapping)
        matched = extra[extra["place_id"].notna()].drop(columns=["name", "lat", "lon"])
        base = base.merge(matched, on="place_id", how="left")
        new = extra[extra["place_id"].isna()].copy()
        new["place_id"] = prefix_id + new[key].astype(str)
        return pd.concat([base, new], ignore_index=True)

    # Official restrooms keep their own name and position (the restroom, not the park
    # centroid or an unnamed OSM toilet node): Phase 2 measures walk time to the restroom.
    official = official.assign(
        official_name=official["name"], official_lat=official["lat"], official_lon=official["lon"]
    )
    places = attach(places, official, "official_id", off_to_osm, "")
    has_off = places["official_id"].notna()
    places.loc[has_off, "lat"] = places.loc[has_off, "official_lat"]
    places.loc[has_off, "lon"] = places.loc[has_off, "official_lon"]
    places.loc[has_off, "name"] = places.loc[has_off, "name"].fillna(
        places.loc[has_off, "official_name"]
    )
    places = places.drop(columns=["official_lat", "official_lon"])
    places.loc[places["place_id"].str.startswith("nyc:"), "category"] = "official_restroom"
    places = attach(places, dohmh, "camis", dohmh_to_osm, "dohmh:")
    places.loc[
        places["place_id"].str.startswith("dohmh:") & places["category"].isna(), "category"
    ] = "dohmh_restaurant"
    # refuge: matches may point at OSM ids or at DOHMH-only places
    places = attach(places, refuge, "refuge_id", refuge_to, "refuge:")
    places.loc[
        places["place_id"].str.startswith("refuge:") & places["category"].isna(), "category"
    ] = "refuge_only"

    places["official_present"] = places["official_id"].notna()
    places["refuge_present"] = places["refuge_id"].notna()
    places["likely_covered_pickup"] = places["camis"].notna()

    # hours: official text first (it's about the restroom), else OSM opening_hours
    hs, hw, hc, hf, src = [], [], [], [], []
    for r in places.itertuples():
        if isinstance(r.hours_confidence, str) and r.hours_confidence != "none":
            hs.append(r.hours_summer), hw.append(r.hours_winter)
            hc.append(r.hours_confidence), hf.append(r.hours_flags), src.append("official")
            continue
        if isinstance(r.osm_opening_hours, str):
            p = hours.parse_osm(r.osm_opening_hours)
            if p.parsed:
                s, w, f = p.summer, p.winter, set(p.flags)
                if r.official_present:  # venue hours, but the restroom's status still rules
                    s, w, f = apply_official_status(s, w, f, r.official_status, r.official_open)
                hs.append(s), hw.append(w)
                hc.append(p.confidence), hf.append(",".join(sorted(f))), src.append("osm")
                continue
        if r.official_present and isinstance(r.hours_summer, str):  # closed/not operational
            hs.append(r.hours_summer), hw.append(r.hours_winter)
            hc.append(r.hours_confidence), hf.append(r.hours_flags), src.append("official")
            continue
        hs.append(None), hw.append(None), hc.append("none"), hf.append(""), src.append(None)
    places["hours_summer"], places["hours_winter"] = hs, hw
    places["hours_confidence"], places["hours_flags"], places["hours_source"] = hc, hf, src

    # borough
    places["borough"] = None
    for g, name in zip(boroughs["the_geom"], boroughs["boroname"], strict=True):
        inside = contains_xy(
            shape(json.loads(g)), places["lon"].to_numpy(), places["lat"].to_numpy()
        )
        places.loc[inside, "borough"] = name

    places.to_parquet(PROCESSED / "places.parquet", index=False)

    # ------------------------------------------------------------------ report numbers
    report["places"] = len(places)
    report["official"] = {
        "rows": len(official),
        "hours_confidence_by_row": official["hours_confidence"].value_counts().to_dict(),
        "season_extension_unknown": int(
            official["hours_flags"].str.contains("season_extension_unknown").sum()
        ),
        "typo_fixed": int(official["hours_flags"].str.contains("typo_fixed").sum()),
        "matched_to_osm": len(ma),
    }
    oh = places[places["hours_source"] == "osm"]
    has_oh = places["osm_opening_hours"].notna()
    report["osm_hours"] = {
        "with_opening_hours_tag": int(has_oh.sum()),
        "parsed": len(oh),
        "parse_rate": round(
            len(oh) / max(1, int((has_oh & (places["hours_source"] != "official")).sum())), 4
        ),
    }
    report["labels"] = {
        "osm_toilets": places["osm_toilets"].value_counts().to_dict(),
        "osm_toilets_access": places["osm_toilets_access"].value_counts().to_dict(),
        "official_present": int(places["official_present"].sum()),
        "refuge_present": int(places["refuge_present"].sum()),
        "likely_covered_pickup": int(places["likely_covered_pickup"].sum()),
    }
    report["borough_counts"] = places["borough"].value_counts(dropna=False).to_dict()

    # fresh sample for re-auditing; the judged copy lives in docs/match_audit.csv
    pd.DataFrame(audit).to_csv(PROCESSED / "match_audit_sample.csv", index=False)
    (DOCS / "phase1_build.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    return report
