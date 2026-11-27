from datetime import date

import numpy as np
import pandas as pd
import pytest

from restrooms import hours
from restrooms.deserts import extend_to_dusk, public_osm_toilets, restroom_sets, share_over
from restrooms.ridership import hour_of_week_means


def mask(open_hours: range, days=range(7)) -> str:
    m = ["0"] * 168
    for d in days:
        for h in open_hours:
            m[d * 24 + h] = "1"
    return "".join(m)


def test_extend_to_dusk_only_days_open_at_1530():
    m = mask(range(8, 16), days=range(5))  # weekdays 8-16
    e = extend_to_dusk(m)
    assert e == mask(range(8, 20), days=range(5))
    assert extend_to_dusk(hours.CLOSED) == hours.CLOSED


def test_share_over_weekday_only_and_weighted():
    minutes = np.zeros((2, 168))
    minutes[1, :] = 20  # station 1 always far
    entries = np.zeros((2, 168))
    for d in range(7):
        entries[0, d * 24 + 9] = 300
        entries[1, d * 24 + 9] = 100
    assert share_over(minutes, entries, 9, 10) == pytest.approx(0.25)
    minutes[1, 5 * 24 + 9] = 0  # Saturday change must not matter
    assert share_over(minutes, entries, 9, 10) == pytest.approx(0.25)


def places_frame():
    rows = [
        # official, operational hours known, "open later seasonally"
        dict(official_present=True, category="official_restroom", hours_summer=mask(range(8, 16)),
             hours_winter=mask(range(8, 16)), hours_flags="season_extension_unknown"),
        # official, no hours
        dict(official_present=True, category="official_restroom", hours_summer=None,
             hours_winter=None, hours_flags="unparseable"),
        # OSM public toilet with hours
        dict(official_present=False, category="amenity=toilets", osm_access="yes",
             hours_source="osm", hours_summer=hours.OPEN_247, hours_winter=hours.OPEN_247),
        # OSM toilet, unknown hours
        dict(official_present=False, category="amenity=toilets", hours_summer=None,
             hours_winter=None),
        # OSM toilet, customers only -> never public
        dict(official_present=False, category="amenity=toilets", osm_access="customers",
             hours_source="osm", hours_summer=hours.OPEN_247, hours_winter=hours.OPEN_247),
        # cafe with customer restroom and hours -> purchase tier only
        dict(official_present=False, category="amenity=cafe", osm_toilets="yes",
             hours_source="osm", hours_summer=mask(range(7, 22)), hours_winter=mask(range(7, 22))),
    ]  # fmt: skip
    df = pd.DataFrame(rows)
    for c in ("osm_access", "osm_fee", "osm_toilets", "osm_toilets_access", "hours_source",
              "hours_flags"):  # fmt: skip
        if c not in df:
            df[c] = None
    df["refuge_present"] = False
    df["lat"] = 40.7 + np.arange(len(df)) * 0.001
    df["lon"] = -73.95
    return df


def test_public_osm_toilets():
    p = places_frame()
    assert public_osm_toilets(p).tolist() == [False, False, True, True, False, False]


def test_restroom_sets_membership_and_readings():
    s = restroom_sets(places_frame())
    assert len(s["primary"].lat) == 2  # official w/ hours + OSM toilet w/ hours
    assert len(s["sensitivity"].lat) == 4  # + official w/o hours + OSM unknown hours
    assert len(s["purchase"].lat) == 3  # primary + cafe
    prim = s["primary"].masks
    h18 = 2 * 24 + 18  # Wednesday 18:00
    assert not prim[("summer", "A")][0, h18]  # closes 16:00
    assert prim[("summer", "B")][0, h18]  # dusk reading: open until 20:00
    assert not prim[("winter", "B")][0, h18]  # B never extends winter
    sens = s["sensitivity"].masks[("summer", "A")]
    assert sens[1].all() and sens[3].all()  # unknown hours counted always open


def test_hour_of_week_means_dow_zero_fill_and_exclusion():
    # Monday 2026-01-05 and Monday 2026-01-12, plus excluded MLK Monday 2026-01-19
    daily = pd.DataFrame(
        {
            "station_complex_id": ["1", "1", "1", "2"],
            "date": [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 5)],
            "hh": [8, 8, 8, 9],
            "entries": [100.0, 300.0, 9999.0, 50.0],
        }
    )
    how = hour_of_week_means(daily, "winter")
    row = how[(how.station_complex_id == "1") & (how.dow == 0) & (how.hh == 8)].iloc[0]
    assert row.mean_entries == pytest.approx(200.0)  # MLK excluded, 2 Mondays
    assert row.how == 8  # Monday = 0
    z = how[(how.station_complex_id == "2") & (how.dow == 0) & (how.hh == 8)].iloc[0]
    assert z.mean_entries == 0  # zero-filled
    assert len(how) == 2 * 7 * 24


def test_weekday_encoding_guard():
    from restrooms.ridership import check_weekday_encoding

    rows = [(d, 8, 1000.0 if d < 5 else 100.0) for d in range(7)]
    good = pd.DataFrame(rows, columns=["dow", "hh", "mean_entries"])
    check_weekday_encoding(good)
    shifted = good.assign(dow=(good["dow"] + 1) % 7)  # Sunday-first misread
    with pytest.raises(AssertionError):
        check_weekday_encoding(shifted)
