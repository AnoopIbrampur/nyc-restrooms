import numpy as np
import pandas as pd
import pytest

from restrooms.audit import draw
from restrooms.audit_score import select_scored
from restrooms.categories import CUISINE_CLASS, fine_class, group_of
from restrooms.likelihood import FLOOR, HierRate, labels, three_class


def test_fine_class_and_groups():
    assert fine_class("dohmh_restaurant", "Coffee/Tea") == "amenity=cafe"
    assert fine_class("dohmh_restaurant", "Pizza") == "amenity=fast_food"
    assert fine_class("dohmh_restaurant", "Thai") == "amenity=restaurant"
    assert fine_class("amenity=bar", None) == "amenity=bar"
    assert group_of("amenity=pub") == "bar"
    assert group_of("shop=bicycle") == "retail"  # any other shop
    assert group_of("leisure=playground") is None  # outside the universe
    assert all(group_of(v) is not None for v in CUISINE_CLASS.values())


def test_labels_mapping():
    u = pd.DataFrame(
        {
            "osm_toilets": ["yes", "yes", "customers", "no", "yes", None, "yes"],
            "osm_toilets_access": ["permissive", "customers", None, None, None, None, "private"],
        }
    )
    lab = labels(u)
    assert lab["s1"].tolist()[:5] == [1, 1, 1, 0, 1]
    assert np.isnan(lab["s1"][5])
    assert lab["s1"][6] == 0  # private -> none
    assert lab["s2"][0] == 1 and lab["s2"][1] == 0 and lab["s2"][2] == 0
    assert np.isnan(lab["s2"][4])  # yes without access tag: stage 1 only
    assert np.isnan(lab["s2"][3])


def test_hier_rate_shrinks_toward_parent():
    fine = pd.Series(["a"] * 2 + ["b"] * 100)
    grp = pd.Series(["g"] * 102)
    y = pd.Series([1, 1] + [0] * 100)
    h = HierRate.fit(fine, grp, y)
    pa = h.predict(pd.Series(["a"]), pd.Series(["g"]))[0]
    # two positives with 10 pseudo-counts toward a low group rate -> far below 1
    assert 0.1 < pa < 0.3
    unseen = h.predict(pd.Series(["zzz"]), pd.Series(["g"]))[0]
    assert unseen == pytest.approx(h.grp["g"])
    assert h.predict(pd.Series(["zzz"]), pd.Series(["nogroup"]))[0] == pytest.approx(h.glob)


def test_three_class_floor_and_sum():
    p = three_class(np.array([1.0, 0.0]), np.array([1.0, 0.5]))
    assert np.allclose(p.sum(axis=1), 1)
    assert (p >= FLOOR / (1 + 2 * FLOOR)).all()


def test_draw_is_seeded_and_ordered():
    u = pd.DataFrame(
        {
            "place_id": [f"p{i}" for i in range(800)],
            "group": np.repeat(
                ["restaurant", "quick_service", "cafe_bakery", "bar", "grocery", "retail",
                 "services_health", "lodging_culture_civic"], 100),
        }
    )  # fmt: skip
    a, b = draw(u), draw(u)
    assert a["place_id"].tolist() == b["place_id"].tolist()
    g = a[a["group"] == "bar"]
    assert (g["reserve_rank"] == 0).sum() == 25
    assert sorted(g.loc[g["reserve_rank"] > 0, "reserve_rank"]) == list(range(1, 16))


def _sheet(outcomes_main, outcomes_res, group="bar"):
    rows = [
        dict(audit_id=f"m{i}", group=group, reserve_rank=0, place_id=f"m{i}", outcome=o,
             answer="free" if o == "answered" else "")
        for i, o in enumerate(outcomes_main)
    ] + [
        dict(audit_id=f"r{i}", group=group, reserve_rank=i + 1, place_id=f"r{i}", outcome=o,
             answer="none" if o == "answered" else "")
        for i, o in enumerate(outcomes_res)
    ]  # fmt: skip
    return pd.DataFrame(rows)


def test_reserves_replace_unreachable_in_order():
    s = _sheet(["answered"] * 23 + ["no_answer", "closed"], ["answered", "closed", "answered"])
    kept, stats = select_scored(s)
    assert len(kept) == 25
    assert set(kept["audit_id"]) >= {"r0", "r2"} and "r1" not in set(kept["audit_id"])
    assert stats["unreachable"]["bar"] == 3


def test_reserve_skipped_is_an_error():
    s = _sheet(["answered"] * 24 + ["no_answer"], ["", "answered"])  # rank 1 skipped
    with pytest.raises(ValueError):
        select_scored(s)


def test_blank_cells_from_csv_are_handled():
    s = _sheet(["answered"] * 24 + ["no_answer"], ["answered", "", ""])
    s["outcome"] = s["outcome"].replace("", pd.NA).astype("string")  # as read from a CSV
    kept, _ = select_scored(s)
    assert len(kept) == 25
