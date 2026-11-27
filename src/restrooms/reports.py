"""Delivery-worker restroom reports: storage-agnostic aggregation + publishing rule.

Raw reports never leave the server. The worker page only receives `public_summary()`
output, which applies the rule below. This keeps a single report, or one person
reporting many times, from putting a named business on a public map.

Report = (place_id, outcome, device, ip, date). No free text and no location beyond the
place. `device` is a random per-browser token; `ip` is a keyed, truncated hash of the
network address (HMAC with a server secret), never the address itself. Both are needed
because a device token alone can be reset by clearing browser storage.

Publishing rule (all in `public_summary`):
- Window: reports from the last WINDOW_DAYS.
- One vote per device per place: a device's latest report for that place in the window
  (ties on the same day broken by submission order, `seq`).
- A place is listed only if at least MIN_DEVICES_PLACE distinct devices report it, at least
  MIN_REFUSED_PLACE of them say "refused" from at least MIN_REFUSED_PLACE distinct ip
  hashes, refusals are at least MIN_REFUSED_SHARE of that place's devices, and the place
  isn't contested.
- Contested places (the business disputed reports) are withheld until reviewed.
- Area rollups (H3 resolution 7, about 5 km2) are published only with at least MIN_AREA_REPORTS
  device-votes from at least MIN_AREA_DEVICES devices and as many ip hashes. They give the
  refused share only.
- "kitchen_exception" (staff said the restroom is through the kitchen) is a legal
  exception, not a refusal, and is counted separately, never as a refusal.
- Public wording: "workers reported being refused here", never "violates the law".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import h3
import pandas as pd

OUTCOMES = ("let_in", "refused", "kitchen_exception", "no_restroom")
WINDOW_DAYS = 180
MIN_DEVICES_PLACE = 3
MIN_REFUSED_PLACE = 3
MIN_REFUSED_SHARE = 0.5
MIN_AREA_REPORTS = 10
MIN_AREA_DEVICES = 5
AREA_RES = 7


@dataclass(frozen=True)
class Report:
    place_id: str
    outcome: str
    device: str
    day: date
    ip: str | None = None  # None (tests/back-compat): treated as one hash per device
    seq: int = 0  # submission order, breaks same-day ties

    def __post_init__(self):
        if self.outcome not in OUTCOMES:
            raise ValueError(f"bad outcome {self.outcome!r}")


def _votes(reports: list[Report], today: date) -> pd.DataFrame:
    """Latest report per (device, place) within the window."""
    cutoff = today - timedelta(days=WINDOW_DAYS)
    rows = [
        (
            r.place_id,
            r.outcome,
            r.device,
            r.ip if r.ip is not None else f"dev:{r.device}",
            r.day,
            r.seq,
            i,
        )
        for i, r in enumerate(reports)
        if cutoff < r.day <= today
    ]
    df = pd.DataFrame(rows, columns=["place_id", "outcome", "device", "ip", "day", "seq", "pos"])
    if df.empty:
        return df
    df = (
        df.sort_values(["day", "seq", "pos"])
        .groupby(["device", "place_id"], as_index=False)
        .tail(1)
    )
    return df


def public_summary(
    reports: list[Report],
    places: pd.DataFrame,
    today: date,
    contested: set[str] = frozenset(),
) -> dict:
    """places: DataFrame with place_id, name, lat, lon (only listed places need a name)."""
    v = _votes(reports, today)
    out = {
        "as_of": today.isoformat(),
        "window_days": WINDOW_DAYS,
        "rule": {
            "min_devices_place": MIN_DEVICES_PLACE,
            "min_refused_place": MIN_REFUSED_PLACE,
            "min_refused_share": MIN_REFUSED_SHARE,
            "min_area_reports": MIN_AREA_REPORTS,
            "min_area_devices": MIN_AREA_DEVICES,
        },
        "places": [],
        "areas": [],
        "withheld_contested": 0,
    }
    if v.empty:
        return out
    info = places.set_index("place_id")

    for pid, g in v.groupby("place_id"):
        n = g["device"].nunique()
        ref = g[g["outcome"] == "refused"]
        refused = len(ref)
        refused_ips = ref["ip"].nunique()
        if (
            n < MIN_DEVICES_PLACE
            or refused < MIN_REFUSED_PLACE
            or refused_ips < MIN_REFUSED_PLACE
            or refused / n < MIN_REFUSED_SHARE
        ):
            continue
        if pid in contested:
            out["withheld_contested"] += 1
            continue
        if pid not in info.index:
            continue
        p = info.loc[pid]
        out["places"].append(
            {
                "place_id": pid,
                "name": str(p["name"]) if pd.notna(p["name"]) else "Unnamed business",
                "lat": round(float(p["lat"]), 5),
                "lon": round(float(p["lon"]), 5),
                "refused": refused,
                "let_in": int((g["outcome"] == "let_in").sum()),
                "kitchen_exception": int((g["outcome"] == "kitchen_exception").sum()),
                "reporters": int(n),
                "first": g["day"].min().isoformat(),
                "last": g["day"].max().isoformat(),
            }
        )

    known = v[v["place_id"].isin(info.index)].copy()
    if not known.empty:
        ll = info.loc[known["place_id"], ["lat", "lon"]].to_numpy()
        known["cell"] = [h3.latlng_to_cell(a, b, AREA_RES) for a, b in ll]
        for cell, g in known.groupby("cell"):
            if (
                len(g) < MIN_AREA_REPORTS
                or g["device"].nunique() < MIN_AREA_DEVICES
                or g["ip"].nunique() < MIN_AREA_DEVICES
            ):
                continue
            decided = g[g["outcome"].isin(["let_in", "refused"])]
            if decided.empty:
                continue
            n_ref = int((decided["outcome"] == "refused").sum())
            out["areas"].append(
                {
                    "h3": cell,
                    "refused": n_ref,
                    "decided": int(len(decided)),
                    "refused_share": round(n_ref / len(decided), 2),
                    "votes": int(len(g)),
                }
            )
    out["places"].sort(key=lambda d: (-d["refused"], d["place_id"]))
    out["areas"].sort(key=lambda d: d["h3"])
    return out
