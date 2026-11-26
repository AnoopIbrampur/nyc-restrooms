from pathlib import Path

import pytest
from shapely.geometry import box

from restrooms.osm import extract, summary_counts

FIXTURE = Path(__file__).parent / "fixtures" / "mini.osm"
SQUARE = box(-74.0, 40.7, -73.9, 40.8)


@pytest.fixture(scope="module")
def result():
    return extract(FIXTURE, SQUARE)


def test_keeps_tagged_inside(result):
    df, _ = result
    assert sorted(df["osm_id"]) == [1, 2, 100]


def test_way_centroid_excludes_closing_node(result):
    df, _ = result
    w = df[df["osm_id"] == 100].iloc[0]
    assert w["osm_type"] == "way"
    assert w["lat"] == pytest.approx(40.73) and w["lon"] == pytest.approx(-73.93)


def test_columns_and_tags(result):
    df, stats = result
    cafe = df[df["osm_id"] == 1].iloc[0]
    assert cafe["t_toilets"] == "yes" and cafe["t_toilets_access"] == "customers"
    assert '"name": "Bean Co"' in cafe["tags"]
    assert stats["relations_skipped"] == 1


def test_summary_counts(result):
    df, _ = result
    c = summary_counts(df)
    assert c["amenity_toilets"] == 1 and c["toilets_yes"] == 1 and c["toilets_no"] == 1
    assert c["food_places"] == 1 and c["shops"] == 1
