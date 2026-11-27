"""Pedestrian network from the OSM extract, plus multi-source walking times.

Graph: every node of a walkable `highway` way inside the NYC bounding box is a vertex;
consecutive way nodes are joined by an undirected edge weighted by its length in metres.
Components smaller than MIN_COMPONENT nodes (sidewalk fragments) are dropped before
snapping, so points snap only to the connected network. Staten Island stays its own
component (no walkway on the Verrazzano) and that's correct: it can't reach the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import osmium
from scipy.sparse import coo_matrix, csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from restrooms.match import M_PER_DEG_LAT, M_PER_DEG_LON

NYC_BBOX = (-74.26, 40.49, -73.70, 40.92)
WALK_SPEED_MPS = 1.25  # pre-registered
MIN_COMPONENT = 1_000  # pre-registered

EXCLUDED_HIGHWAY = {
    "motorway", "motorway_link", "construction", "proposed", "raceway", "demolished",
    "abandoned", "platform", "bus_guideway", "busway", "services", "rest_area",
}  # fmt: skip
TRUNK = {"trunk", "trunk_link"}


def walkable(tags: dict[str, str]) -> bool:
    hw = tags.get("highway")
    if not hw or hw in EXCLUDED_HIGHWAY:
        return False
    foot = tags.get("foot")
    if foot == "no":
        return False
    if hw in TRUNK and foot not in ("yes", "designated", "permissive"):
        return False
    if tags.get("access") in ("private", "no") and foot not in ("yes", "designated", "permissive"):
        return False
    return True


@dataclass
class WalkGraph:
    graph: csr_matrix  # metres, undirected (symmetric)
    lon: np.ndarray
    lat: np.ndarray
    keep: np.ndarray  # bool: node is in a component >= MIN_COMPONENT
    component: np.ndarray

    def _xy(self) -> np.ndarray:
        return np.column_stack([self.lon * M_PER_DEG_LON, self.lat * M_PER_DEG_LAT])

    def snap(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Nearest kept node for each point -> (node index, snap distance in metres)."""
        idx_keep = np.flatnonzero(self.keep)
        tree = cKDTree(self._xy()[idx_keep])
        pts = np.column_stack([np.asarray(lon) * M_PER_DEG_LON, np.asarray(lat) * M_PER_DEG_LAT])
        d, j = tree.query(pts)
        return idx_keep[j], d

    def save(self, path: Path) -> None:
        g = self.graph.tocoo()
        np.savez_compressed(
            path, row=g.row, col=g.col, w=g.data, lon=self.lon, lat=self.lat,
            keep=self.keep, component=self.component, n=g.shape[0],
        )  # fmt: skip

    @classmethod
    def load(cls, path: Path) -> WalkGraph:
        z = np.load(path)
        n = int(z["n"])
        g = coo_matrix((z["w"], (z["row"], z["col"])), shape=(n, n)).tocsr()
        return cls(g, z["lon"], z["lat"], z["keep"], z["component"])


def _undirected(r: np.ndarray, c: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> csr_matrix:
    """Symmetric edge-length matrix; a segment shared by two ways is counted once."""
    a, b = np.minimum(r, c), np.maximum(r, c)
    pairs = np.unique(np.column_stack([a, b]), axis=0)
    a, b = pairs[:, 0], pairs[:, 1]
    length = np.hypot((lon[a] - lon[b]) * M_PER_DEG_LON, (lat[a] - lat[b]) * M_PER_DEG_LAT)
    length = np.maximum(length, 1e-3)  # zero would read as "no edge" in a sparse matrix
    n = len(lon)
    return coo_matrix(
        (np.concatenate([length, length]), (np.concatenate([a, b]), np.concatenate([b, a]))),
        shape=(n, n),
    ).tocsr()


def build_graph(
    pbf: Path, bbox=NYC_BBOX, min_component: int = MIN_COMPONENT
) -> tuple[WalkGraph, dict]:
    minx, miny, maxx, maxy = bbox
    node_index: dict[int, int] = {}
    lons: list[float] = []
    lats: list[float] = []
    rows: list[int] = []
    cols: list[int] = []
    ways = 0

    def nid(ref: int, lon: float, lat: float) -> int:
        i = node_index.get(ref)
        if i is None:
            i = len(lons)
            node_index[ref] = i
            lons.append(lon)
            lats.append(lat)
        return i

    fp = (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    for w in fp:
        tags = {t.k: t.v for t in w.tags}
        if not walkable(tags):
            continue
        pts = [(n.ref, n.lon, n.lat) for n in w.nodes if n.location.valid()]
        if len(pts) < 2:
            continue
        if not any(minx <= lo <= maxx and miny <= la <= maxy for _, lo, la in pts):
            continue
        ways += 1
        prev = nid(*pts[0])
        for ref, lo, la in pts[1:]:
            cur = nid(ref, lo, la)
            if cur != prev:
                rows.append(prev)
                cols.append(cur)
            prev = cur

    lon, lat = np.array(lons), np.array(lats)
    g = _undirected(np.array(rows), np.array(cols), lon, lat)
    n = len(lon)
    ncomp, labels = connected_components(g, directed=False)
    sizes = np.bincount(labels)
    keep = sizes[labels] >= min_component
    stats = {
        "ways": ways,
        "nodes": n,
        "edges": int(g.nnz // 2),
        "components": int(ncomp),
        "components_kept": int((sizes >= min_component).sum()),
        "nodes_kept": int(keep.sum()),
        "largest_components": sorted(sizes.tolist(), reverse=True)[:5],
    }
    return WalkGraph(g, lon, lat, keep, labels), stats


def nearest_source_distance(
    g: WalkGraph, source_nodes: np.ndarray, source_snap_m: np.ndarray
) -> np.ndarray:
    """Metres from every node to the nearest source, including that source's snap leg.

    A virtual node is linked to each source's network node with an edge equal to the
    source's snap distance; one Dijkstra from the virtual node then gives
    min over sources of (snap + network distance). inf = unreachable.
    """
    n = g.graph.shape[0]
    if len(source_nodes) == 0:
        return np.full(n, np.inf)
    # several sources can snap to one node: keep the shortest leg
    best: dict[int, float] = {}
    for node, d in zip(np.asarray(source_nodes), np.asarray(source_snap_m), strict=True):
        best[int(node)] = min(best.get(int(node), np.inf), float(d))
    nodes = np.fromiter(best.keys(), dtype=np.int64)
    legs = np.maximum(np.fromiter(best.values(), dtype=float), 1e-3)
    v = n  # virtual node index
    if not hasattr(g, "_coo"):
        coo = g.graph.tocoo()
        g._coo = (coo.row, coo.col, coo.data)
    row, col, data = g._coo
    big = coo_matrix(
        (
            np.concatenate([data, legs]),
            (np.concatenate([row, np.full(len(nodes), v)]), np.concatenate([col, nodes])),
        ),
        shape=(n + 1, n + 1),
    ).tocsr()
    dist = dijkstra(big, directed=True, indices=v)  # edges out of v only; graph is symmetric
    return dist[:n]


def walk_minutes(dist_from_sources: np.ndarray, node: np.ndarray, snap_m: np.ndarray) -> np.ndarray:
    """Minutes = (network metres incl. source snap + this point's snap) / speed."""
    return (dist_from_sources[node] + snap_m) / WALK_SPEED_MPS / 60.0


BRIDGES = {
    # name: (Manhattan-side point, other-side point)
    "Brooklyn": ((40.7128, -74.0045), (40.6995, -73.9897)),
    "Manhattan": ((40.7163, -73.9955), (40.7020, -73.9870)),
    "Williamsburg": ((40.7180, -73.9860), (40.7105, -73.9600)),
    "Queensboro": ((40.7600, -73.9620), (40.7520, -73.9400)),
}


def network_checks(g: WalkGraph, seed: int = 0, n_src: int = 40, per_src: int = 50) -> dict:
    """Pre-registered sanity checks: detour ratio on random pairs 1-5 km apart in the main
    component, and that the East River bridge walkways connect."""
    sizes = np.bincount(g.component)
    main = np.flatnonzero(g.component == np.argmax(sizes))
    rng = np.random.default_rng(seed)
    src = rng.choice(main, n_src, replace=False)
    dist = dijkstra(g.graph, directed=False, indices=src)
    xy = np.column_stack([g.lon * M_PER_DEG_LON, g.lat * M_PER_DEG_LAT])
    ratios = []
    for k, s in enumerate(src):
        cand = rng.choice(main, 2000, replace=False)
        e = np.hypot(*(xy[cand] - xy[s]).T)
        ok = (e > 1000) & (e < 5000)
        ratios.extend((dist[k, cand[ok]] / e[ok])[:per_src].tolist())
    r = np.array(ratios)
    bridges = {}
    for name, (a, b) in BRIDGES.items():
        (na,), _ = g.snap(np.array([a[0]]), np.array([a[1]]))
        (nb,), _ = g.snap(np.array([b[0]]), np.array([b[1]]))
        d = float(dijkstra(g.graph, directed=False, indices=na)[nb])
        bridges[name] = {
            "network_m": round(d),
            "straight_m": round(float(np.hypot(*(xy[na] - xy[nb])))),
            "connected": bool(np.isfinite(d)),
        }
    return {
        "detour_pairs": len(r),
        "detour_median": round(float(np.median(r)), 3),
        "detour_p90": round(float(np.percentile(r, 90)), 3),
        "detour_p99": round(float(np.percentile(r, 99)), 3),
        "detour_share_over_3": round(float((r > 3).mean()), 4),
        "unreachable_pairs": int(np.isinf(r).sum()),
        "bridges": bridges,
    }
