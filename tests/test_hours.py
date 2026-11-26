"""Hours parser tests. Every NYC string here is copied from the real dataset (i7jb-7jku)."""

import pytest

from restrooms.hours import (
    CLOSED,
    OPEN_247,
    hours_open,
    parse_nyc,
    parse_osm,
)

D = "MTWTFSS"


def days(mask: str) -> str:
    """Mask -> 'M:8-16 T:8-16 ... S:x' (first open hour to last open hour + 1)."""
    out = []
    for d in range(7):
        hs = [h for h in range(24) if mask[d * 24 + h] == "1"]
        out.append(f"{D[d]}:{hs[0]}-{hs[-1] + 1}" if hs else f"{D[d]}:x")
    return " ".join(out)


def daily(a: int, b: int) -> str:
    return " ".join(f"{d}:{a}-{b}" for d in D)


# --- NYC free text -----------------------------------------------------------
@pytest.mark.parametrize(
    "text, summer, conf",
    [
        ("7am-10pm", daily(7, 22), "high"),
        ("9:00am-5:00pm", daily(9, 17), "high"),
        ("6:00am-8:00pm Daily", daily(6, 20), "high"),
        ("Everyday 8:00 am-10:00 pm", daily(8, 22), "high"),
        ("9am - 4:30pm", daily(9, 16), "high"),  # open at 16:30? no -> last open hour 15
        ("Open M-F, 8am-8pm", "M:8-20 T:8-20 W:8-20 T:8-20 F:8-20 S:x S:x", "high"),
        ("10 am to 5 pm on weedays", "M:10-17 T:10-17 W:10-17 T:10-17 F:10-17 S:x S:x", "high"),
        ("TUES-SUN 12pm-10pm", "M:x T:12-22 W:12-22 T:12-22 F:12-22 S:12-22 S:12-22", "high"),
        ("Weekends, 10am-1pm", "M:x T:x W:x T:x F:x S:10-13 S:10-13", "high"),
        (
            "Sun, Mon, Weds: 9:30am - 10pm; Tues, Thurs-Sat: 9:30am - 8pm",
            "M:9-22 T:9-20 W:9-22 T:9-20 F:9-20 S:9-20 S:9-22",
            "high",
        ),
        (
            "Monday to Friday, 9:00 am to 8:00 pm, Saturday, 10:00 am to 8:00 pm, "
            "and Sunday, 11:00 am to 7:00 pm",
            "M:9-20 T:9-20 W:9-20 T:9-20 F:9-20 S:10-20 S:11-19",
            "high",
        ),
        (
            "Monday\t10 am - 6 pm\nTuesday\t1 pm - 8 pm\nWednesday\t10 am - 6 pm\n"
            "Thursday\t10 am - 8 pm\nFriday\t10 am - 6 pm\nSaturday\t10 am - 5 pm\nSunday\tCLOSED",
            "M:10-18 T:13-20 W:10-18 T:10-20 F:10-18 S:10-17 S:x",
            "high",
        ),
    ],
)
def test_nyc_parses(text, summer, conf):
    h = parse_nyc(text)
    assert days(h.summer) == summer
    assert h.confidence == conf


def test_season_extension_flagged_not_invented():
    h = parse_nyc("8am-4pm, Open later seasonally")
    assert days(h.summer) == daily(8, 16) and h.winter == h.summer
    assert "season_extension_unknown" in h.flags and h.confidence == "medium"


def test_dusk_differs_by_season():
    h = parse_nyc("7am - dusk")
    assert days(h.summer) == daily(7, 20)
    assert days(h.winter) == daily(7, 17)
    assert "dusk" in h.flags and h.confidence == "medium"


def test_slash_dusk_takes_earlier():
    h = parse_nyc("7:30am - 8:30pm/dusk")
    assert days(h.summer) == daily(7, 20)  # dusk (20:00) earlier than 20:30


def test_overnight_wraps():
    h = parse_nyc("6 AM – 1 AM")
    assert h.summer[0] == "1"  # Monday 00:30 open (Sunday's late hours)
    assert h.summer[1] == "0"  # Monday 01:30 closed
    assert h.summer[6] == "1"  # Monday 06:30 open
    assert hours_open(h.summer) == 7 * 19


def test_seasonal_blocks():
    h = parse_nyc("March-October: 7am - 11pm, November-March: 7am - 10pm")
    assert days(h.summer) == daily(7, 23)
    assert days(h.winter) == daily(7, 22)
    h = parse_nyc("Fall, spring summer: 7am - 9pm. Winter: 7am - 5:30pm")
    assert days(h.summer) == daily(7, 21)
    assert days(h.winter) == daily(7, 17)


def test_pm_typo_fixed_and_flagged():
    text = (
        "Sunday: Closed \nMonday: 10:00 am - 6:00 pm \nTuesday: 10:00 pm - 6:00 pm \n"
        "Wednesday: 10:00 am - 6:00 pm \nThursday: 10:00 pm - 6:00 pm \n"
        "Friday: 10:00 am - 6:00 pm \nSaturday: 10:00 am - 6:00 pm"
    )
    h = parse_nyc(text)
    assert days(h.summer) == "M:10-18 T:10-18 W:10-18 T:10-18 F:10-18 S:10-18 S:x"
    assert "typo_fixed" in h.flags and h.confidence == "medium"


def test_pm_typo_not_fixed_without_support():
    # no other day starts at 10am -> leave it (end < start = overnight), never guess
    text = "Monday: 11:00 am - 6:00 pm\nTuesday: 10:00 pm - 6:00 pm\nWednesday: 11:00 am - 6:00 pm"
    assert "typo_fixed" not in parse_nyc(text).flags


def test_midday_closure_carved_out():
    h = parse_nyc(
        "Bathrooms are open from 7 a.m.-7 p.m., with a one-hour closure for cleaning "
        "from 12 noon-1 p.m."
    )
    assert h.summer[12] == "0" and h.summer[11] == "1" and h.summer[13] == "1"
    assert "midday_closure" in h.flags


def test_ambiguous_ranges_flagged():
    h = parse_nyc("6am - 12am, 8am - 10pm")
    assert "ambiguous_ranges" in h.flags and h.confidence == "medium"
    h = parse_nyc("M-T 10:00am-2:20pm W-S 10:00am-10:00pm")
    assert "ambiguous_days" in h.flags


@pytest.mark.parametrize(
    "text, flag",
    [
        ("Open by permit", "by_permit"),
        ("https://sifunpark.com/2023-hours/", "unparseable"),
        ("Tuesday-Saturday", "unparseable"),
        ("Open during games and weekends in ball season", "unparseable"),
    ],
)
def test_unusable_text(text, flag):
    h = parse_nyc(text)
    assert h.confidence == "none" and h.summer is None and flag in h.flags


def test_closed_and_247_and_empty():
    assert parse_nyc("Temp Closed").summer == CLOSED
    assert parse_nyc("24 Hours").summer == OPEN_247
    assert parse_nyc("Open 24/7").winter == OPEN_247
    assert parse_nyc(None).confidence == "none"
    assert parse_nyc("  ").confidence == "none"


def test_partial_is_low():
    assert parse_nyc("11:00am - 10:00pm midnight on weekends").confidence == "low"


# --- OSM opening_hours -------------------------------------------------------
def test_osm_basic():
    h = parse_osm("Mo-Fr 08:00-18:00")
    assert days(h.summer) == "M:8-18 T:8-18 W:8-18 T:8-18 F:8-18 S:x S:x"
    assert h.confidence == "high" and h.winter == h.summer


def test_osm_247_and_seasons():
    assert parse_osm("24/7").summer == OPEN_247
    h = parse_osm("Apr-Oct: 07:00-22:00; Nov-Mar: 07:00-17:00")
    assert days(h.summer) == daily(7, 22) and days(h.winter) == daily(7, 17)


def test_osm_sunset_uses_nyc_sun():
    h = parse_osm("sunrise-sunset")
    assert h.summer[0 * 24 + 19] == "1"  # 19:30 in July: before sunset (~20:25)
    assert h.winter[0 * 24 + 17] == "0"  # 17:30 in late Jan: after sunset (~17:10)
    assert "solar" in h.flags


def test_osm_bad():
    assert parse_osm("garbage text").confidence == "none"
    assert parse_osm(None).confidence == "none"
