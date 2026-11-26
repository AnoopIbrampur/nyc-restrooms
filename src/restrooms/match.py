"""One-to-one spatial + name matching between two point tables.

Candidates: pairs within `radius_m`. A candidate is accepted if it passes `rule`
(e.g. name similarity >= 85, or distance-only for unnamed toilets). Accepted
candidates are assigned greedily by score (best first) so each record on either
side is used at most once: two unnamed toilets in one park can't both claim the
same official restroom.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from scipy.spatial import cKDTree

M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = 111_320.0 * np.cos(np.radians(40.7))  # NYC latitude

_STOP = re.compile(
    r"\b(the|inc|llc|corp|co|ltd|restaurant|rest|cafe|bar|grill|kitchen|nyc|ny|"
    r"new york|and|of|&)\b"
)


def house_no(s: object) -> str:
    """Leading house number ('91-18', '262'), normalized; '' if none."""
    if not isinstance(s, str):
        return ""
    m = re.match(r"\s*(\d+(?:\s*-\s*\d+)?)\b", s)
    return re.sub(r"\s+", "", m.group(1)) if m else ""


def norm_name(s: object) -> str:
    if not isinstance(s, str):
        return ""
    t = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    t = t.lower().replace("’", "'")
    t = re.sub(r"#\s*\d+", " ", t)  # store numbers: "jersey mike's #34102"
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", t)  # 17th -> 17
    t = re.sub(r"\bdoctor\b", "dr", t)
    t = re.sub(r"\bone fifty\b", "1 50", t)
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = t.replace("'", "")
    t = _STOP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def name_sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a, b))


def xy(lat: pd.Series, lon: pd.Series) -> np.ndarray:
    return np.column_stack([lon.to_numpy() * M_PER_DEG_LON, lat.to_numpy() * M_PER_DEG_LAT])


@dataclass
class Candidates:
    left: np.ndarray  # positional index into left
    right: np.ndarray
    dist_m: np.ndarray
    sim: np.ndarray


def candidates(
    left: pd.DataFrame, right: pd.DataFrame, radius_m: float, name_col: str = "norm_name"
) -> Candidates:
    if left.empty or right.empty:
        e = np.array([], dtype=int)
        return Candidates(e, e, np.array([]), np.array([]))
    tl, tr = cKDTree(xy(left["lat"], left["lon"])), cKDTree(xy(right["lat"], right["lon"]))
    pairs = tl.query_ball_tree(tr, r=radius_m)
    li, ri = [], []
    for i, js in enumerate(pairs):
        li.extend([i] * len(js))
        ri.extend(js)
    li, ri = np.array(li, dtype=int), np.array(ri, dtype=int)
    if len(li) == 0:
        return Candidates(li, ri, np.array([]), np.array([]))
    a, b = xy(left["lat"], left["lon"])[li], xy(right["lat"], right["lon"])[ri]
    dist = np.hypot(*(a - b).T)
    ln, rn = left[name_col].to_numpy(), right[name_col].to_numpy()
    sim = np.array([name_sim(ln[i], rn[j]) for i, j in zip(li, ri, strict=True)])
    return Candidates(li, ri, dist, sim)


Rule = Callable[[float, float, int, int], bool]  # (dist_m, sim, i, j) -> accept?


def assign(c: Candidates, rule: Rule, radius_m: float) -> pd.DataFrame:
    """Greedy one-to-one assignment. Score = name similarity minus a distance penalty."""
    ok = np.array(
        [rule(d, s, i, j) for d, s, i, j in zip(c.dist_m, c.sim, c.left, c.right, strict=True)],
        dtype=bool,
    )
    score = c.sim - 20.0 * (c.dist_m / radius_m)
    order = np.argsort(-score[ok], kind="stable")
    li, ri, dd, ss, sc = (x[ok][order] for x in (c.left, c.right, c.dist_m, c.sim, score))
    used_l, used_r, out = set(), set(), []
    for i, j, d, s, k in zip(li, ri, dd, ss, sc, strict=True):
        if i in used_l or j in used_r:
            continue
        used_l.add(i)
        used_r.add(j)
        out.append((int(i), int(j), float(d), float(s), float(k)))
    return pd.DataFrame(out, columns=["left", "right", "dist_m", "sim", "score"])


def near_misses(c: Candidates, matched: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Candidate pairs where neither side got matched: used to estimate missed matches."""
    ml, mr = set(matched["left"]), set(matched["right"])
    keep = [k for k in range(len(c.left)) if c.left[k] not in ml and c.right[k] not in mr]
    df = pd.DataFrame(
        {
            "left": c.left[keep],
            "right": c.right[keep],
            "dist_m": c.dist_m[keep],
            "sim": c.sim[keep],
        }
    )
    # the hardest cases: most similar names among the leftovers
    df = df.sort_values("sim", ascending=False).head(n * 5)
    return df.sample(min(n, len(df)), random_state=seed) if len(df) else df
