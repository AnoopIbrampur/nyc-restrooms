import pandas as pd

from restrooms.match import assign, candidates, norm_name

# ~0.0001 deg lat ~ 11 m
BASE_LAT, BASE_LON = 40.75, -73.98


def pts(rows):
    df = pd.DataFrame(rows, columns=["name", "dlat", "dlon"])
    df["lat"] = BASE_LAT + df["dlat"] * 1e-4
    df["lon"] = BASE_LON + df["dlon"] * 1e-4
    df["norm_name"] = df["name"].map(norm_name)
    return df


def test_norm_name():
    assert norm_name("Joe's Pizza, Inc.") == "joes pizza"
    assert norm_name("The Bean Café NYC") == "bean"
    assert norm_name(None) == ""


def test_name_and_distance_rule():
    left = pts([("Joe's Pizza", 0, 0), ("Blue Bottle Coffee", 10, 0)])
    right = pts([("JOES PIZZA INC", 1, 0), ("Starbucks", 10, 1)])
    c = candidates(left, right, radius_m=75)
    m = assign(c, lambda d, s, i, j: s >= 85, 75)
    assert list(zip(m["left"], m["right"], strict=True)) == [(0, 0)]


def test_one_to_one_distance_only():
    # two unnamed toilets near one official restroom: only the closer one matches
    left = pts([("", 0, 0), ("", 3, 0)])
    right = pts([("Charybdis Playground", 1, 0)])
    c = candidates(left, right, radius_m=60)
    m = assign(c, lambda d, s, i, j: True, 60)
    assert len(m) == 1 and m.iloc[0]["left"] == 0


def test_outside_radius_ignored():
    left = pts([("Joe's Pizza", 0, 0)])
    right = pts([("Joe's Pizza", 20, 0)])  # ~220 m away
    assert len(candidates(left, right, radius_m=75).left) == 0
