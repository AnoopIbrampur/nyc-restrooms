from datetime import date, timedelta

import pandas as pd
import pytest

from restrooms.reports import Report, public_summary

TODAY = date(2026, 11, 27)
PLACES = pd.DataFrame(
    {
        "place_id": ["a", "b", "c"] + [f"n{i}" for i in range(12)],
        "name": ["Alpha Deli", "Beta Pizza", "Gamma Cafe"] + [f"N{i}" for i in range(12)],
        "lat": [40.75, 40.7501, 40.7502] + [40.7503 + i * 1e-5 for i in range(12)],
        "lon": [-73.99] * 15,
    }
)


def r(pid, outcome, dev, days_ago=1):
    return Report(pid, outcome, dev, TODAY - timedelta(days=days_ago))


def test_single_report_never_published():
    s = public_summary([r("a", "refused", "d1")], PLACES, TODAY)
    assert s["places"] == []


def test_one_device_spamming_counts_once():
    reps = [r("a", "refused", "d1", days_ago=i) for i in range(1, 30)]
    assert public_summary(reps, PLACES, TODAY)["places"] == []


def test_three_independent_refusals_published_with_counts_only():
    reps = [r("a", "refused", f"d{i}") for i in range(3)] + [r("a", "let_in", "d9")]
    s = public_summary(reps, PLACES, TODAY)
    (p,) = s["places"]
    assert p["name"] == "Alpha Deli" and p["refused"] == 3 and p["let_in"] == 1
    assert p["reporters"] == 4
    assert "device" not in str(p) and "d1" not in str(s)  # no device tokens leak


def test_refused_must_be_at_least_half():
    reps = [r("a", "refused", f"d{i}") for i in range(3)] + [
        r("a", "let_in", f"e{i}") for i in range(4)
    ]
    assert public_summary(reps, PLACES, TODAY)["places"] == []


def test_kitchen_exception_is_not_a_refusal():
    reps = [r("a", "kitchen_exception", f"d{i}") for i in range(5)]
    assert public_summary(reps, PLACES, TODAY)["places"] == []


def test_latest_vote_per_device_wins():
    # device changed its mind: was refused long ago, let in recently
    reps = [r("a", "refused", f"d{i}", days_ago=20) for i in range(3)] + [
        r("a", "let_in", "d0", days_ago=2)
    ]
    assert public_summary(reps, PLACES, TODAY)["places"] == []  # only 2 refusals now


def test_window_excludes_old_reports():
    reps = [r("a", "refused", f"d{i}", days_ago=200) for i in range(5)]
    assert public_summary(reps, PLACES, TODAY)["places"] == []


def test_contested_place_withheld():
    reps = [r("a", "refused", f"d{i}") for i in range(4)]
    s = public_summary(reps, PLACES, TODAY, contested={"a"})
    assert s["places"] == [] and s["withheld_contested"] == 1


def test_area_rollup_needs_volume_and_devices():
    few = [r(f"n{i}", "refused", "d1") for i in range(12)]  # 12 votes, 1 device
    assert public_summary(few, PLACES, TODAY)["areas"] == []
    many = [r(f"n{i}", "refused" if i % 3 else "let_in", f"d{i}") for i in range(12)]
    (a,) = public_summary(many, PLACES, TODAY)["areas"]
    assert a["votes"] == 12 and a["refused_share"] == pytest.approx(8 / 12, abs=0.01)


def test_bad_outcome_rejected():
    with pytest.raises(ValueError):
        Report("a", "violation", "d1", TODAY)


def test_same_network_counts_once_for_listing():
    # three device tokens, one network: looks like one person clearing storage
    reps = [Report("a", "refused", f"d{i}", TODAY - timedelta(days=1), ip="h1") for i in range(3)]
    assert public_summary(reps, PLACES, TODAY)["places"] == []
    reps += [
        Report("a", "refused", "d7", TODAY - timedelta(days=1), ip="h2"),
        Report("a", "refused", "d8", TODAY - timedelta(days=1), ip="h3"),
    ]
    assert len(public_summary(reps, PLACES, TODAY)["places"]) == 1


def test_same_day_tie_broken_by_seq():
    d = TODAY - timedelta(days=1)
    reps = [Report("a", "let_in", f"d{i}", d, seq=10) for i in range(3)]
    reps += [Report("a", "refused", f"d{i}", d, seq=20) for i in range(3)]
    assert len(public_summary(reps, PLACES, TODAY)["places"]) == 1
