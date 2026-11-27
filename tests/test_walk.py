from pathlib import Path

import numpy as np
import pytest

from restrooms.match import M_PER_DEG_LON
from restrooms.walk import (
    WALK_SPEED_MPS,
    build_graph,
    nearest_source_distance,
    walk_minutes,
    walkable,
)

FIX = Path(__file__).parent / "fixtures" / "walk.osm"
STEP = 0.001 * M_PER_DEG_LON  # metres per 0.001 deg lon


@pytest.fixture(scope="module")
def built():
    return build_graph(FIX, min_component=3)


def test_walkable_rules():
    assert walkable({"highway": "footway"})
    assert not walkable({"highway": "motorway"})
    assert not walkable({"highway": "trunk"})
    assert walkable({"highway": "trunk", "foot": "yes"})
    assert not walkable({"highway": "service", "access": "private"})
    assert walkable({"highway": "service", "access": "private", "foot": "yes"})
    assert not walkable({"highway": "path", "foot": "no"})


def test_graph_shape(built):
    g, stats = built
    # nodes: A B C F (main) + G H (fragment); D/E only on excluded ways
    assert stats["nodes"] == 6
    assert stats["edges"] == 4  # A-B, B-C (deduped), C-F, G-H
    assert stats["components"] == 2 and stats["components_kept"] == 1
    assert g.keep.sum() == 4


def test_distance_no_motorway_shortcut_no_double_count(built):
    g, _ = built
    a, _ = g.snap(np.array([40.75]), np.array([-73.990]))
    c, _ = g.snap(np.array([40.75]), np.array([-73.988]))
    d = nearest_source_distance(g, c, np.array([0.0]))
    assert d[a[0]] == pytest.approx(2 * STEP, rel=1e-3)


def test_source_snap_leg_added_and_min_taken(built):
    g, _ = built
    a, _ = g.snap(np.array([40.75]), np.array([-73.990]))
    c, _ = g.snap(np.array([40.75]), np.array([-73.988]))
    # source at A with a 500 m leg vs source at C with 0 leg: A's own distance = min(500, 2 steps)
    d = nearest_source_distance(g, np.array([a[0], c[0]]), np.array([500.0, 0.0]))
    assert d[a[0]] == pytest.approx(min(500.0, 2 * STEP), rel=1e-3)


def test_fragment_not_snapped_and_unreachable(built):
    g, _ = built
    node, snap = g.snap(np.array([40.76]), np.array([-73.95]))
    assert g.keep[node[0]] and snap[0] > 1000  # snapped to main network, far away
    c, _ = g.snap(np.array([40.75]), np.array([-73.988]))
    assert np.isinf(nearest_source_distance(g, np.array([], dtype=int), np.array([]))).all()
    m = walk_minutes(nearest_source_distance(g, c, np.array([0.0])), node, snap)
    assert np.isfinite(m[0])


def test_walk_minutes():
    m = walk_minutes(np.array([750.0]), np.array([0]), np.array([0.0]))
    assert m[0] == pytest.approx(750 / WALK_SPEED_MPS / 60)
