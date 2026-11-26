"""Registry of every external data source the project depends on.

Rule: a source goes in here only after a live check confirmed it resolves
(see `restrooms check-sources`). Expected fields are the columns later phases
rely on; the check fails if any disappear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    SOCRATA = "socrata"  # NYC / NY State open data (SODA API)
    FILE = "file"  # plain HTTP download
    API = "api"  # JSON API, checked with a small sample request


@dataclass(frozen=True)
class Source:
    key: str
    kind: Kind
    title: str
    url: str  # Socrata: domain; FILE/API: full URL
    phase: int  # first phase that uses it
    dataset_id: str = ""  # Socrata 4x4 id
    expected_fields: tuple[str, ...] = ()
    notes: str = ""
    params: dict[str, str] = field(default_factory=dict)  # API sample params

    @property
    def resource_url(self) -> str:
        if self.kind is Kind.SOCRATA:
            return f"https://{self.url}/resource/{self.dataset_id}.json"
        return self.url

    @property
    def metadata_url(self) -> str:
        if self.kind is not Kind.SOCRATA:
            raise ValueError(f"{self.key}: metadata only exists for Socrata sources")
        return f"https://{self.url}/api/views/{self.dataset_id}.json"


NYC = "data.cityofnewyork.us"
NYS = "data.ny.gov"

SOURCES: tuple[Source, ...] = (
    # --- restrooms -------------------------------------------------------
    Source(
        "nyc_restrooms",
        Kind.SOCRATA,
        "Public Restrooms",
        NYC,
        1,
        "i7jb-7jku",
        (
            "facility_name",
            "location_type",
            "operator",
            "status",
            "latitude",
            "longitude",
            "hours_of_operation",
            "accessibility",
            "changing_stations",
        ),
        "~1,100 rows; hours are free text and need parsing.",
    ),
    Source(
        "parks_restroom_sites",
        Kind.SOCRATA,
        "Parks Inspection Program – Public Restrooms",
        NYC,
        1,
        "9byw-znpj",
    ),
    Source(
        "parks_restroom_inspections",
        Kind.SOCRATA,
        "Parks Inspection Program – Public Restroom Inspections",
        NYC,
        1,
        "mp8v-wjtf",
    ),
    Source(
        "parks_restroom_ratings",
        Kind.SOCRATA,
        "Parks Inspection Program – Public Restroom Feature Ratings",
        NYC,
        1,
        "xmiz-qy72",
    ),
    Source(
        "parks_restroom_hazards",
        Kind.SOCRATA,
        "Parks Inspection Program – Public Restroom Conditions & Hazards",
        NYC,
        1,
        "r8mb-budb",
    ),
    Source(
        "parks_inspections",
        Kind.SOCRATA,
        "Parks Inspection Program – Inspections",
        NYC,
        2,
        "yg3y-7juh",
        ("inspection_id", "begininspection"),
        "Inspection dates; links restroom inspections to time. Join deferred to Phase 2.",
    ),
    Source(
        "parks_sites",
        Kind.SOCRATA,
        "Parks Inspection Program – All Sites (MAPPED)",
        NYC,
        2,
        "buk3-3qpr",
        ("propnum", "multipolygon"),
        "Park property polygons for the condition-layer spatial join (Phase 2).",
    ),
    Source(
        "refuge",
        Kind.API,
        "Refuge Restrooms (by location)",
        "https://www.refugerestrooms.org/api/v1/restrooms/by_location",
        1,
        expected_fields=(
            "name",
            "latitude",
            "longitude",
            "accessible",
            "unisex",
            "changing_table",
            "created_at",
        ),
        notes="Crowdsourced, mostly 2014-2019 in NYC: weak/stale labels.",
        params={"lat": "40.7549", "lng": "-73.9840", "per_page": "5"},
    ),
    # --- places ----------------------------------------------------------
    Source(
        "osm_extract",
        Kind.FILE,
        "Geofabrik New York State OSM extract",
        "https://download.geofabrik.de/north-america/us/new-york/new-york-latest.osm.pbf",
        1,
        notes="Bulk OSM source (clip to NYC). Public Overpass is for small queries only.",
    ),
    Source(
        "dohmh_restaurants",
        Kind.SOCRATA,
        "DOHMH Restaurant Inspection Results",
        NYC,
        1,
        "43nn-pn8j",
        (
            "camis",
            "dba",
            "boro",
            "building",
            "street",
            "zipcode",
            "cuisine_description",
            "inspection_date",
            "latitude",
            "longitude",
        ),
        "~31.5k distinct CAMIS; universe for delivery-worker mode.",
    ),
    Source(
        "building_footprints",
        Kind.SOCRATA,
        "Building Footprints (BUILDING)",
        NYC,
        3,
        "5zhs-2jue",
        ("bin", "the_geom", "shape_area", "height_roof", "base_bbl"),
        "Footprint area as a model feature.",
    ),
    # --- demand / geography ---------------------------------------------
    Source(
        "mta_hourly",
        Kind.SOCRATA,
        "MTA Subway Hourly Ridership: Beginning 2025",
        NYS,
        2,
        "5wq4-mkjj",
        (
            "transit_timestamp",
            "station_complex_id",
            "station_complex",
            "ridership",
            "latitude",
            "longitude",
        ),
        "Hourly entries per station complex; main foot-traffic weight.",
    ),
    Source(
        "mta_stations",
        Kind.SOCRATA,
        "MTA Subway Stations",
        NYS,
        2,
        "39hk-dx4f",
        ("complex_id", "stop_name", "gtfs_latitude", "gtfs_longitude", "ada"),
    ),
    Source(
        "ped_counts",
        Kind.SOCRATA,
        "DOT Bi-Annual Pedestrian Counts",
        NYC,
        2,
        "cqsj-cfgu",
        ("the_geom", "borough", "street_nam"),
        "Coarse: ~114 fixed spots, AM/MD/PM, twice a year. Secondary weight only.",
    ),
    Source(
        "boroughs",
        Kind.SOCRATA,
        "Borough Boundaries",
        NYC,
        2,
        "gthc-hcne",
        ("borocode", "boroname", "the_geom"),
    ),
)


def by_key(key: str) -> Source:
    for s in SOURCES:
        if s.key == key:
            return s
    raise KeyError(key)
