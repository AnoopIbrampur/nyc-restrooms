"""Phase 3: restroom-likelihood model vs hierarchical category baseline (docs/phase3_prereg.md).

Two stages, each a binary probability:
  stage 1: P(usable restroom)       labels from OSM toilets / toilets:access
  stage 2: P(free | has restroom)   labels from OSM toilets:access
Three classes: free = s1*s2, customers = s1*(1-s2), none = 1-s1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import h3
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from restrooms.audit import audited_place_ids, universe
from restrooms.match import M_PER_DEG_LAT, M_PER_DEG_LON, norm_name
from restrooms.paths import DOCS, PROCESSED, RAW

PSEUDO = 10.0  # pre-registered smoothing strength
FLOOR = 0.005  # pre-registered probability floor
CLASSES = ("free", "customers", "none")
FREE_ACCESS = {"yes", "public", "permissive"}
NO_ACCESS = {"private", "no"}
# logistic C per stage, chosen by grouped-CV grid {0.02..1.0} on OSM labels (2026-11-27):
# stage 1 log-loss 0.3641 (C=.02) ... 0.3216 (.5), 0.3209 (1.0); stage 2 best 0.5565 at C=.2
LOGIT_C = {"s1": 1.0, "s2": 0.2}
# Which prediction later phases use. "baseline" until the pre-registered audit shows the
# model beats it (docs/phase3_interim.md). Changing this needs an audit result.
SHIPPED = "baseline"
CHAIN_MIN = 5  # a normalized name seen >= 5 times in the universe = chain
TOP_CHAINS = 60
TOP_CLASSES = 80
CAT_COLS = ["fine_class_c", "group", "chain_c", "borough"]
NUM_COLS = [
    "is_chain", "open_hours", "has_hours", "open_late", "dohmh", "dohmh_only",
    "refuge", "log_area", "height", "has_bin", "log_density", "dist_subway", "is_way",
]  # fmt: skip


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
def labels(u: pd.DataFrame) -> pd.DataFrame:
    t, a = u["osm_toilets"], u["osm_toilets_access"]
    s1 = pd.Series(np.nan, index=u.index)
    s1[t.isin(["yes", "customers"])] = 1
    s1[(t == "no") | a.isin(NO_ACCESS)] = 0
    s2 = pd.Series(np.nan, index=u.index)
    has = s1 == 1
    s2[has & a.isin(FREE_ACCESS)] = 1
    s2[has & ((a == "customers") | (t == "customers"))] = 0
    return pd.DataFrame({"s1": s1, "s2": s2})


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def features(u: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=u.index)
    f["group"] = u["group"]
    top_cls = u["fine_class"].value_counts().head(TOP_CLASSES).index
    f["fine_class_c"] = np.where(
        u["fine_class"].isin(top_cls), u["fine_class"], "other_" + u["group"]
    )
    brand = u["osm_brand"].where(u["osm_brand"].notna(), u["name"])
    key = brand.map(norm_name)
    counts = key[key != ""].value_counts()
    chains = counts[counts >= CHAIN_MIN]
    f["is_chain"] = key.isin(chains.index).astype(float)
    f["chain_c"] = np.where(key.isin(chains.head(TOP_CHAINS).index), key, "none")
    f["chain_key"] = np.where(f["is_chain"] == 1, key, "")
    f["borough"] = u["borough"].fillna("unknown")
    mask = u["hours_summer"]
    f["has_hours"] = mask.notna().astype(float)
    f["open_hours"] = mask.map(lambda m: m.count("1") if isinstance(m, str) else np.nan)
    f["open_late"] = mask.map(
        lambda m: (
            float(any(m[d * 24 + 22] == "1" for d in range(5))) if isinstance(m, str) else np.nan
        )
    )
    f["dohmh"] = u["camis"].notna().astype(float)
    f["dohmh_only"] = u["place_id"].str.startswith("dohmh:").astype(float)
    f["refuge"] = u["refuge_present"].astype(float)
    f["is_way"] = (u["osm_type"] == "way").astype(float)

    # building footprint via DOHMH BIN or OSM nycdoitt:bin
    fp = pd.read_parquet(RAW / "footprints_by_bin.parquet").set_index("bin")
    bins = _bins(u)
    area = bins.map(fp["shape_area"])
    f["has_bin"] = area.notna().astype(float)
    f["log_area"] = np.log1p(area)
    f["height"] = bins.map(fp["height_roof"])

    xy = np.column_stack([u["lon"] * M_PER_DEG_LON, u["lat"] * M_PER_DEG_LAT])
    tree = cKDTree(xy)
    f["log_density"] = np.log1p([len(n) - 1 for n in tree.query_ball_point(xy, r=150)])
    st = pd.read_parquet(RAW / "subway_stations.parquet")
    st_xy = np.column_stack([st["lon"] * M_PER_DEG_LON, st["lat"] * M_PER_DEG_LAT])
    f["dist_subway"] = cKDTree(st_xy).query(xy)[0]
    f["cell7"] = [h3.latlng_to_cell(la, lo, 7) for la, lo in zip(u["lat"], u["lon"], strict=True)]
    return f


def _bins(u: pd.DataFrame) -> pd.Series:
    d = pd.read_parquet(RAW / "dohmh_restaurants.parquet", columns=["camis", "bin"])
    d = d.dropna().drop_duplicates("camis").set_index("camis")["bin"]
    o = pd.read_parquet(PROCESSED / "osm_places.parquet", columns=["osm_type", "osm_id", "tags"])
    o["place_id"] = "osm:" + o["osm_type"] + ":" + o["osm_id"].astype(str)
    osm_bin = {
        pid: json.loads(t).get("nycdoitt:bin")
        for pid, t in zip(o["place_id"], o["tags"], strict=True)
        if "nycdoitt:bin" in t
    }
    out = u["camis"].map(d)
    fill = u["place_id"].map(osm_bin)
    out = out.where(out.notna(), fill)
    return out.astype("string").str.split(";").str[0]


def cv_groups(f: pd.DataFrame) -> np.ndarray:
    return np.where(f["chain_key"] != "", "chain:" + f["chain_key"], "cell:" + f["cell7"])


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------
@dataclass
class HierRate:
    """fine class -> group -> global, each level shrunk toward its parent by PSEUDO."""

    glob: float
    grp: dict
    fine: dict

    @classmethod
    def fit(cls, fine: pd.Series, grp: pd.Series, y: pd.Series) -> HierRate:
        glob = float(y.mean())
        g = y.groupby(grp).agg(["sum", "count"])
        grp_rate = ((g["sum"] + PSEUDO * glob) / (g["count"] + PSEUDO)).to_dict()
        df = pd.DataFrame({"fine": fine, "grp": grp, "y": y})
        fr = df.groupby(["fine", "grp"])["y"].agg(["sum", "count"]).reset_index()
        fine_rate = {
            (r.fine, r.grp): (r["sum"] + PSEUDO * grp_rate.get(r.grp, glob)) / (r["count"] + PSEUDO)
            for _, r in fr.iterrows()
        }
        return cls(glob, grp_rate, fine_rate)

    def predict(self, fine: pd.Series, grp: pd.Series) -> np.ndarray:
        out = []
        for a, b in zip(fine, grp, strict=True):
            out.append(self.fine.get((a, b), self.grp.get(b, self.glob)))
        return np.array(out)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def make_model(kind: str, C: float = 0.5):
    if kind == "logit":
        pre = ColumnTransformer(
            [
                ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=3), CAT_COLS),
                (
                    "num",
                    make_pipeline(
                        SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler()
                    ),
                    NUM_COLS,
                ),
            ]
        )
        return make_pipeline(pre, LogisticRegression(C=C, max_iter=2000))
    if kind == "gbm":
        pre = ColumnTransformer(
            [
                (
                    "cat",
                    OneHotEncoder(handle_unknown="ignore", min_frequency=3, sparse_output=False),
                    CAT_COLS,
                ),
                ("num", "passthrough", NUM_COLS),
            ]
        )
        return make_pipeline(
            pre,
            HistGradientBoostingClassifier(
                max_depth=3,
                learning_rate=0.05,
                max_iter=200,
                l2_regularization=1.0,
                min_samples_leaf=20,
            ),
        )
    raise ValueError(kind)


def three_class(s1: np.ndarray, s2: np.ndarray) -> np.ndarray:
    p = np.column_stack([s1 * s2, s1 * (1 - s2), 1 - s1])
    p = np.maximum(p, FLOOR)
    return p / p.sum(axis=1, keepdims=True)


def cv_compare(f: pd.DataFrame, y: pd.Series, C: float, n_splits: int = 5) -> dict:
    """Grouped CV log-loss for baseline / logit / gbm on one stage."""
    m = y.notna()
    X, yy, groups = f[m], y[m].astype(int), cv_groups(f[m])
    oof = {k: np.zeros(len(yy)) for k in ("baseline", "logit", "gbm")}
    for tr, te in GroupKFold(n_splits=n_splits).split(X, yy, groups):
        b = HierRate.fit(X["fine_class_c"].iloc[tr], X["group"].iloc[tr], yy.iloc[tr])
        oof["baseline"][te] = b.predict(X["fine_class_c"].iloc[te], X["group"].iloc[te])
        for k in ("logit", "gbm"):
            mod = make_model(k, C).fit(X.iloc[tr], yy.iloc[tr])
            oof[k][te] = mod.predict_proba(X.iloc[te])[:, 1]
    clip = lambda p: np.clip(p, FLOOR, 1 - FLOOR)  # noqa: E731
    return {
        "n": int(len(yy)),
        "positive_rate": round(float(yy.mean()), 3),
        **{k: round(float(log_loss(yy, clip(v), labels=[0, 1])), 4) for k, v in oof.items()},
    }


def run() -> dict:
    u = universe()
    lab = labels(u)
    f = features(u)
    audited = u["place_id"].isin(audited_place_ids()).to_numpy()
    train = ~audited
    report = {
        "universe": len(u),
        "audit_rows_excluded_from_training": int(audited.sum()),
        "labels_stage1": int(lab["s1"][train].notna().sum()),
        "labels_stage2": int(lab["s2"][train].notna().sum()),
        "audit_rows_with_osm_label": int(lab["s1"][audited].notna().sum()),
    }
    report["cv_stage1"] = cv_compare(f[train], lab["s1"][train], LOGIT_C["s1"])
    report["cv_stage2"] = cv_compare(f[train], lab["s2"][train], LOGIT_C["s2"])
    report["logit_C"] = LOGIT_C
    choice = {
        s: min(("logit", "gbm"), key=lambda k: report[f"cv_{s}"][k]) for s in ("stage1", "stage2")
    }
    report["model_choice"] = choice

    preds = {}
    for stage, col in (("stage1", "s1"), ("stage2", "s2")):
        m = train & lab[col].notna().to_numpy()
        y = lab[col][m].astype(int)
        base = HierRate.fit(f["fine_class_c"][m], f["group"][m], y)
        model = make_model(choice[stage], LOGIT_C[col]).fit(f[m], y)
        preds[f"base_{col}"] = base.predict(f["fine_class_c"], f["group"])
        preds[f"model_{col}"] = model.predict_proba(f)[:, 1]
    pm = three_class(preds["model_s1"], preds["model_s2"])
    pb = three_class(preds["base_s1"], preds["base_s2"])
    out = pd.DataFrame(
        {"place_id": u["place_id"], "group": u["group"], "fine_class": u["fine_class"]}
    )
    for i, c in enumerate(CLASSES):
        out[f"model_{c}"] = pm[:, i].round(5)
        out[f"base_{c}"] = pb[:, i].round(5)
        # what downstream phases use: the baseline until the audit says otherwise
        out[f"use_{c}"] = out[f"{'model' if SHIPPED == 'model' else 'base'}_{c}"]
    out["use_source"] = SHIPPED
    out.to_parquet(PROCESSED / "restroom_likelihood.parquet", index=False)

    report["mean_predicted"] = {
        "model": {c: round(float(pm[:, i].mean()), 3) for i, c in enumerate(CLASSES)},
        "baseline": {c: round(float(pb[:, i].mean()), 3) for i, c in enumerate(CLASSES)},
    }
    report["mean_by_group_model"] = (
        out.groupby("group")[[f"model_{c}" for c in CLASSES]]
        .mean()
        .round(3)
        .to_dict(orient="index")
    )
    (DOCS / "phase3_model.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=1))
    return report
