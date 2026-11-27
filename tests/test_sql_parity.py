"""The server's SQL publishing rule must give exactly the Python reference's result."""

import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import h3
import pandas as pd
import pytest

from restrooms import reports as R

BACKEND = Path(__file__).resolve().parents[1] / "backend"
TODAY = date(2026, 11, 27)


def rules():
    return json.loads((BACKEND / "rules.json").read_text())


def test_rules_json_matches_python_constants():
    r = rules()
    assert r["window_days"] == R.WINDOW_DAYS
    assert r["min_devices_place"] == R.MIN_DEVICES_PLACE
    assert r["min_refused_place"] == R.MIN_REFUSED_PLACE
    assert r["min_refused_share"] == R.MIN_REFUSED_SHARE
    assert r["min_area_reports"] == R.MIN_AREA_REPORTS
    assert r["min_area_devices"] == R.MIN_AREA_DEVICES


def make_db(places: pd.DataFrame, reps: list[R.Report], disputed=()) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript((BACKEND / "schema.sql").read_text())
    db.executemany(
        "INSERT INTO places VALUES (?,?,?,?,?)",
        [
            (p.place_id, p.name, p.lat, p.lon, h3.latlng_to_cell(p.lat, p.lon, R.AREA_RES))
            for p in places.itertuples()
        ],
    )
    # insertion order = submission order: sort by (seq, original position) like Python does
    order = sorted(range(len(reps)), key=lambda i: (reps[i].seq, i))
    db.executemany(
        "INSERT INTO reports (place_id, outcome, device, iphash, day) VALUES (?,?,?,?,?)",
        [
            (
                reps[i].place_id,
                reps[i].outcome,
                reps[i].device,
                reps[i].ip if reps[i].ip is not None else f"dev:{reps[i].device}",
                reps[i].day.isoformat(),
            )
            for i in order
        ],
    )
    db.executemany(
        "INSERT INTO disputes (place_id, day) VALUES (?, ?)", [(d, "2026-11-01") for d in disputed]
    )
    return db


def sql_summary(db: sqlite3.Connection) -> dict:
    r = rules()
    q = (BACKEND / "sql" / "public_places.sql").read_text()
    rows = db.execute(
        q,
        (TODAY.isoformat(), r["window_days"], r["min_devices_place"], r["min_refused_place"],
         r["min_refused_share"]),
    ).fetchall()  # fmt: skip
    places = [
        {"place_id": x[0], "refused": x[4], "let_in": x[5], "kitchen_exception": x[6],
         "reporters": x[7], "first": x[8], "last": x[9]}
        for x in rows if not x[10]
    ]  # fmt: skip
    withheld = sum(1 for x in rows if x[10])
    qa = (BACKEND / "sql" / "public_areas.sql").read_text()
    areas = [
        {"h3": a[0], "votes": a[1], "refused": a[2], "decided": a[3]}
        for a in db.execute(
            qa, (TODAY.isoformat(), r["window_days"], r["min_area_reports"], r["min_area_devices"])
        )
    ]
    return {"places": places, "areas": areas, "withheld": withheld}


def py_summary(places, reps, disputed=()) -> dict:
    s = R.public_summary(reps, places, TODAY, contested=set(disputed))
    keep = ("place_id", "refused", "let_in", "kitchen_exception", "reporters", "first", "last")
    return {
        "places": [{k: p[k] for k in keep} for p in s["places"]],
        "areas": [{k: a[k] for k in ("h3", "votes", "refused", "decided")} for a in s["areas"]],
        "withheld": s["withheld_contested"],
    }


def random_case(seed: int):
    rng = random.Random(seed)
    n_places = rng.randint(1, 8)
    places = pd.DataFrame(
        {
            "place_id": [f"p{i}" for i in range(n_places)],
            "name": [f"Place {i}" for i in range(n_places)],
            # cluster places so some share an H3-7 cell
            "lat": [40.75 + rng.choice([0, 0.0005, 0.05]) + i * 1e-5 for i in range(n_places)],
            "lon": [-73.99 + rng.choice([0, 0.0005, 0.05]) for _ in range(n_places)],
        }
    )
    reps = []
    for k in range(rng.randint(0, 80)):
        reps.append(
            R.Report(
                place_id=rng.choice(places["place_id"]),
                outcome=rng.choices(R.OUTCOMES, weights=[3, 5, 1, 1])[0],
                device=f"d{rng.randint(0, 12)}",
                day=TODAY - timedelta(days=rng.choice([0, 1, 2, 5, 30, 179, 180, 181, 400])),
                ip=f"h{rng.randint(0, 6)}",
                seq=k,
            )
        )
    disputed = [p for p in places["place_id"] if rng.random() < 0.15]
    return places, reps, disputed


@pytest.mark.parametrize("seed", range(300))
def test_sql_matches_python_randomized(seed):
    places, reps, disputed = random_case(seed)
    db = make_db(places, reps, disputed)
    assert sql_summary(db) == py_summary(places, reps, disputed)


def test_parity_case_is_not_trivial():
    """Guard: the random cases must actually list places and areas sometimes."""
    listed = areas = 0
    for seed in range(300):
        places, reps, disputed = random_case(seed)
        s = py_summary(places, reps, disputed)
        listed += bool(s["places"])
        areas += bool(s["areas"])
    assert listed > 20 and areas > 20
