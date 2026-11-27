"""Server SQL for restroom confirmations (run on SQLite, like D1)."""

import json
import sqlite3
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
TODAY = "2026-11-27"


def run(rows):
    db = sqlite3.connect(":memory:")
    db.executescript((BACKEND / "schema.sql").read_text())
    db.executemany(
        "INSERT INTO confirmations (restroom_id, kind, device, iphash, day) VALUES (?,?,?,?,?)",
        rows,
    )
    r = json.loads((BACKEND / "rules.json").read_text())
    q = (BACKEND / "sql" / "public_confirmations.sql").read_text()
    cols = ["restroom_id", "open_n", "last_open", "closed_n", "needs_code_n", "clean_n", "dirty_n"]
    out = db.execute(q, (TODAY, r["confirm_window_days"], r["min_closed_votes"])).fetchall()
    return {row[0]: dict(zip(cols, row, strict=True)) for row in out}


def test_cleanliness_does_not_erase_availability():
    s = run([("r1", "open", "d1", "h1", TODAY), ("r1", "clean", "d1", "h1", TODAY)])
    assert s["r1"]["open_n"] == 1 and s["r1"]["clean_n"] == 1


def test_latest_vote_wins_within_a_question():
    s = run(
        [
            ("r1", "open", "d1", "h1", "2026-11-20"),
            ("r1", "closed", "d1", "h1", TODAY),
            ("r1", "dirty", "d1", "h1", "2026-11-20"),
            ("r1", "clean", "d1", "h1", TODAY),
        ]
    )
    assert s["r1"]["open_n"] == 0 and s["r1"]["clean_n"] == 1 and s["r1"]["dirty_n"] == 0


def test_closed_needs_three_devices_and_networks():
    two = run([("r1", "closed", f"d{i}", f"h{i}", TODAY) for i in range(2)])
    assert two["r1"]["closed_n"] == 0
    same_net = run([("r1", "closed", f"d{i}", "h1", TODAY) for i in range(3)])
    assert same_net["r1"]["closed_n"] == 0
    three = run([("r1", "closed", f"d{i}", f"h{i}", TODAY) for i in range(3)])
    assert three["r1"]["closed_n"] == 3


def test_window_and_last_open():
    s = run([("r1", "open", "d1", "h1", "2026-08-01"), ("r1", "open", "d2", "h2", "2026-11-10")])
    assert s["r1"]["open_n"] == 1 and s["r1"]["last_open"] == "2026-11-10"
