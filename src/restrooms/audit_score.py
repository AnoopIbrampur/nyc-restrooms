"""Phase 3 scoring, written before any audit outcome existed (docs/phase3_prereg.md).

freeze(): writes model + baseline probabilities for every audit row (sample and reserves)
          to docs/phase3_frozen_predictions.csv. Scoring uses only that file.
score():  reads the filled audit sheet, applies the reserve rule, and computes the
          pre-registered metrics and outcome.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from restrooms.audit import PER_GROUP, SHEET
from restrooms.categories import GROUPS
from restrooms.likelihood import CLASSES, FLOOR
from restrooms.paths import DOCS, PROCESSED

FROZEN = DOCS / "phase3_frozen_predictions.csv"
N_BOOT = 10_000
BOOT_SEED = 20261127
ANSWERS = {"free": 0, "customers": 1, "none": 2}
REPLACE = {"no_answer", "closed", "refused"}


def freeze() -> pd.DataFrame:
    sheet = pd.read_csv(SHEET)
    pred = pd.read_parquet(PROCESSED / "restroom_likelihood.parquet")
    cols = ["place_id"] + [f"{w}_{c}" for w in ("model", "base") for c in CLASSES]
    out = sheet[["audit_id", "group", "reserve_rank", "place_id"]].merge(
        pred[cols], on="place_id", how="left"
    )
    if out[cols[1:]].isna().any().any():
        raise ValueError("missing predictions for some audit rows")
    out.to_csv(FROZEN, index=False)
    return out


def _floor(p: np.ndarray) -> np.ndarray:
    p = np.maximum(p, FLOOR)
    return p / p.sum(axis=1, keepdims=True)


def select_scored(sheet: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Per group: answered main-sample rows, plus reserves in rank order replacing each
    unreachable main row. Raises if a reserve was skipped or used out of order."""
    sheet = sheet.copy()
    for c in ("outcome", "answer"):
        sheet[c] = sheet[c].astype("string").fillna("").str.strip()  # blank cells -> ""
    keep, stats = [], {"unreachable": {}, "short": {}}
    for g in GROUPS:
        rows = sheet[sheet["group"] == g].sort_values("reserve_rank")
        main = rows[rows["reserve_rank"] == 0]
        res = rows[rows["reserve_rank"] > 0]
        bad = int(main["outcome"].isin(REPLACE).sum())
        answered = main[main["outcome"] == "answered"]
        need = PER_GROUP - len(answered)
        used = res[res["outcome"] != ""]
        ranks = sorted(used["reserve_rank"])
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f"{g}: reserves used out of order: {ranks}")
        res_answered = used[used["outcome"] == "answered"].head(need)
        keep += [answered, res_answered]
        stats["unreachable"][g] = bad + int(used["outcome"].isin(REPLACE).sum())
        if len(answered) + len(res_answered) < PER_GROUP:
            stats["short"][g] = PER_GROUP - len(answered) - len(res_answered)
    return pd.concat(keep), stats


def _logloss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(p[np.arange(len(y)), y])


def _brier(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    onehot = np.eye(3)[y]
    return ((p - onehot) ** 2).sum(axis=1)


def score(universe_counts: dict[str, int]) -> dict:
    sheet = pd.read_csv(SHEET, dtype={"outcome": "string", "answer": "string"})
    frozen = pd.read_csv(FROZEN)
    sheet["outcome"] = sheet["outcome"].fillna("")
    scored, stats = select_scored(sheet)
    scored = scored.merge(frozen, on=["audit_id", "group", "reserve_rank", "place_id"])
    y = scored["answer"].map(ANSWERS)
    if y.isna().any():
        raise ValueError("answered rows must have answer in free/customers/none")
    y = y.to_numpy(int)
    pm = _floor(scored[[f"model_{c}" for c in CLASSES]].to_numpy())
    pb = _floor(scored[[f"base_{c}" for c in CLASSES]].to_numpy())
    grp = scored["group"].to_numpy()
    total = sum(universe_counts.values())
    w_g = {g: universe_counts[g] / total for g in GROUPS}

    def weighted(per_row: np.ndarray, idx: np.ndarray | None = None) -> float:
        idx = np.arange(len(per_row)) if idx is None else idx
        v, gg = per_row[idx], grp[idx]
        return float(sum(w_g[g] * v[gg == g].mean() for g in GROUPS if (gg == g).any()))

    metrics = {}
    rng = np.random.default_rng(BOOT_SEED)
    strata = {g: np.flatnonzero(grp == g) for g in GROUPS}
    for name, fn in (("logloss", _logloss), ("brier", _brier)):
        lm, lb = fn(pm, y), fn(pb, y)
        delta = weighted(lb) - weighted(lm)
        boots = np.empty(N_BOOT)
        for b in range(N_BOOT):
            idx = np.concatenate([rng.choice(ix, len(ix), replace=True) for ix in strata.values()])
            boots[b] = weighted(lb, idx) - weighted(lm, idx)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        metrics[name] = {
            "model": round(weighted(lm), 4),
            "baseline": round(weighted(lb), 4),
            "delta": round(delta, 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "unweighted_model": round(float(lm.mean()), 4),
            "unweighted_baseline": round(float(lb.mean()), 4),
        }
    lo, hi = metrics["logloss"]["ci95"]
    outcome = "beats baseline" if lo > 0 else "loses" if hi < 0 else "not supported"
    s1m = 1 - pm[:, 2]
    s1b = 1 - pb[:, 2]
    has = (y != 2).astype(int)
    result = {
        "n_scored": int(len(y)),
        "outcome": outcome,
        "metrics": metrics,
        "per_group_logloss": {
            g: {
                "model": round(float(_logloss(pm, y)[grp == g].mean()), 4),
                "baseline": round(float(_logloss(pb, y)[grp == g].mean()), 4),
                "n": int((grp == g).sum()),
            }
            for g in GROUPS
            if (grp == g).any()
        },
        "stage1_binary_logloss": {
            "model": round(float(-np.mean(has * np.log(s1m) + (1 - has) * np.log(1 - s1m))), 4),
            "baseline": round(float(-np.mean(has * np.log(s1b) + (1 - has) * np.log(1 - s1b))), 4),
        },
        "answer_counts": pd.Series(scored["answer"]).value_counts().to_dict(),
        "unreachable_by_group": stats["unreachable"],
        "groups_short_of_25": stats["short"],
        "closed_rate": round(
            float((sheet["outcome"] == "closed").sum() / max(1, (sheet["outcome"] != "").sum())), 3
        ),
    }
    (DOCS / "phase3_audit_result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
