import pandas as pd
import pytest

from restrooms import hours
from restrooms.app_data import ValidationError, build, stable_id, validate


def official(n=900, hours_text="7am-10pm", status="Operational"):
    return pd.DataFrame(
        {
            "facility_name": [f"Park {i}" for i in range(n)],
            "location_type": "Park",
            "latitude": [40.70 + i * 1e-4 for i in range(n)],
            "longitude": -73.95,
            "status": status,
            "open": "Year Round",
            "hours_of_operation": hours_text,
            "accessibility": ["Fully Accessible", "Not Accessible", None] * (n // 3),
            "changing_stations": ['"Yes, in women\'s restroom only"', "No", None] * (n // 3),
            "restroom_type": [
                "Single-Stall All Gender Restroom(s)",
                "Multi-Stall W/M Restrooms",
                None,
            ]
            * (n // 3),
        }
    )


SNAP = [
    {"id": f"osm:node:{i}", "name": None, "lat": 40.6 + i * 1e-4, "lon": -73.9,
     "opening_hours": None, "wheelchair": "limited", "changing_table": None, "unisex": "yes",
     "access": None, "fee": None}
    for i in range(400)
]  # fmt: skip


def test_stable_id_ignores_row_order_and_case():
    assert stable_id("Bryant Park", 40.753601, -73.98) == stable_id(" bryant park", 40.7536, -73.98)


def test_build_maps_fields_with_explicit_unknown():
    rows = build(official(), SNAP)
    nyc = [r for r in rows if r["src"] == "nyc"]
    assert [r["acc"] for r in nyc[:3]] == ["yes", "no", "unknown"]
    assert [r["chg"] for r in nyc[:3]] == ["yes", "no", "unknown"]
    assert [r["gn"] for r in nyc[:3]] == ["yes", "no", "unknown"]
    osm = [r for r in rows if r["src"] == "osm"]
    assert osm[0]["acc"] == "limited" and osm[0]["gn"] == "yes" and osm[0]["s"] is None
    assert validate(rows)["official"] == 900


def test_closed_rows_dropped_and_duplicates_collapsed():
    df = official()
    df.loc[0, "status"] = "Not Operational"
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)  # exact duplicate row
    rows = build(df, SNAP)
    assert sum(r["src"] == "nyc" for r in rows) == 899


def test_validation_gate_blocks_bad_data():
    with pytest.raises(ValidationError):
        validate(build(official(n=300), SNAP))  # too few rows
    with pytest.raises(ValidationError):
        validate(build(official(hours_text="call ahead"), SNAP))  # hours mostly unparseable
    rows = build(official(), SNAP)
    rows[0]["la"] = 0.0
    with pytest.raises(ValidationError):
        validate(rows)


def test_masks_well_formed():
    for r in build(official(), SNAP):
        if r["s"]:
            assert len(r["s"]) == hours.HOURS
