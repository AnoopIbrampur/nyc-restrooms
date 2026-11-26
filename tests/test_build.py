import pandas as pd

from restrooms import hours
from restrooms.build import business_rule, clean_official, is_venue, official_rule, refuge_spam


def osm_rows(rows):
    cols = ["category", "t_toilets", "t_toilets_access", "t_amenity", "t_leisure", "t_access"]
    return pd.DataFrame(rows, columns=cols)


def test_is_venue():
    df = osm_rows(
        [
            ("amenity=bench", None, None, "bench", None, None),  # street furniture
            ("amenity=cafe", None, None, "cafe", None, None),  # venue
            ("leisure=swimming_pool", None, None, None, "swimming_pool", "private"),
            ("leisure=swimming_pool", None, None, None, "swimming_pool", "yes"),  # public pool
            ("amenity=parking", "yes", None, "parking", None, None),  # has toilets tag
            ("amenity=toilets", None, None, "toilets", None, None),
        ]
    )
    assert is_venue(df).tolist() == [False, True, False, True, True, True]


def test_refuge_spam():
    raw = pd.DataFrame({"street": ["xMUBmLhTsAKaAZMiIk", "425 Lafayette", "Broadway", None]})
    assert refuge_spam(raw).tolist() == [True, False, False, False]


def test_official_status_overrides_hours():
    raw = pd.DataFrame(
        {
            "facility_name": ["A", "B", "C"],
            "latitude": ["40.7", "40.7", "40.7"],
            "longitude": ["-73.9", "-73.9", "-73.9"],
            "location_type": ["Park"] * 3,
            "operator": ["NYC Parks"] * 3,
            "status": ["Operational", "Not Operational", "Operational"],
            "open": ["Seasonal", "Year Round", "Year Round"],
            "hours_of_operation": ["8am-4pm, Open later seasonally", "7am-10pm", "7am-10pm"],
        }
    )
    df = clean_official(raw)
    a, b, c = df.iloc[0], df.iloc[1], df.iloc[2]
    assert a["hours_winter"] == hours.CLOSED and a["hours_summer"] != hours.CLOSED
    assert "seasonal_closed_winter" in a["hours_flags"]
    assert "season_extension_unknown" in a["hours_flags"]
    assert b["hours_summer"] == hours.CLOSED and "not_operational" in b["hours_flags"]
    assert hours.hours_open(c["hours_summer"]) == 7 * 15


def test_official_rule():
    left = pd.DataFrame({"official_location_type": ["Library", "Park", "Park"]})
    right = pd.DataFrame(
        {
            "t_amenity": ["library", "restaurant", "toilets", None],
            "t_leisure": [None, None, None, "park"],
        }
    )
    rule = official_rule(left, right)
    assert rule(30, 50, 0, 0)  # library <-> OSM library, generic name, close
    assert not rule(30, 90, 0, 1)  # library never matches a restaurant
    assert rule(50, 0, 1, 2) and not rule(70, 0, 1, 2)  # unnamed toilets: <= 60 m
    assert rule(40, 75, 2, 3)  # park <-> park-like, moderate name sim
    assert not rule(40, 75, 2, 1)  # park <-> restaurant needs sim >= 85


def test_business_rule_house_number():
    left = pd.DataFrame({"house_no": ["212", "19"]})
    right = pd.DataFrame({"house_no": ["212", "21"]})
    rule = business_rule(85)(left, right)
    assert rule(10, 90, 0, 1)  # high sim alone is enough
    assert rule(10, 70, 0, 0)  # same house number + sim >= 65
    assert not rule(10, 70, 1, 1)  # different house number
    assert not rule(10, 60, 0, 0)  # sim too low even with same number


def test_official_status_beats_any_hours_source():
    from restrooms.build import apply_official_status

    open_mask = hours.OPEN_247
    s, w, f = apply_official_status(open_mask, open_mask, set(), "Not Operational", "Year Round")
    assert s == w == hours.CLOSED and "not_operational" in f
    s, w, f = apply_official_status(open_mask, open_mask, set(), "Operational", "Seasonal")
    assert s == open_mask and w == hours.CLOSED and "seasonal_closed_winter" in f
    s, w, f = apply_official_status(open_mask, open_mask, set(), "Operational", "Future")
    assert s == w == hours.CLOSED
    s, w, f = apply_official_status(None, None, set(), "Operational", "Seasonal")
    assert s is None and w == hours.CLOSED  # summer unknown, winter known closed
    assert apply_official_status(open_mask, open_mask, set(), "Operational", "Year Round")[0] == (
        open_mask
    )
