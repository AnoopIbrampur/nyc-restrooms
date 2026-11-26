"""Opening hours -> weekly open masks for two reference seasons.

A mask is a 168-char string of '0'/'1': index = weekday*24 + hour, Monday 00:00 = 0,
local NYC time. Hour h is "open" if the place is open at h:30.

Two masks per place: SUMMER (week of 2026-07-13) and WINTER (week of 2027-01-25). Both weeks
contain no US public holidays, so OSM `PH` rules don't distort them.

Two parsers:
- `parse_osm(...)`: OSM `opening_hours` syntax, evaluated with opening-hours-py (handles
  sunset/dusk with NYC coordinates and `PH` with country=US).
- `parse_nyc(...)`: the free text in NYC's Public Restrooms dataset. Rule-based; every
  assumption is reported in `flags` and lowers `confidence`.

Confidence: high = parsed with no assumptions; medium = parsed, but some assumption
(see flags); low = only part of the text understood; none = nothing usable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from opening_hours import OpeningHours, ParserError, State

NY = ZoneInfo("America/New_York")
NYC_COORDS = (40.7128, -74.0060)
SUMMER_WEEK = datetime(2026, 7, 13, tzinfo=NY)  # Monday
WINTER_WEEK = datetime(2027, 1, 25, tzinfo=NY)  # Monday
HOURS = 168

# Dusk for free-text "dusk" in each reference week, rounded *down* to the hour so the
# mask never claims a restroom is open after it actually closes.
# (NYC sunset ~20:25 mid-July, ~17:10 late January.)
DUSK_MINUTES = {"summer": 20 * 60, "winter": 17 * 60}

# "8am-4pm, Open later seasonally" covers ~56% of official restrooms. We do NOT invent the
# later closing time: base hours are used in both seasons and the row is flagged
# `season_extension_unknown`. Phase 2 reports results under both readings.
SEASON_EXTENSION_ASSUMPTION = "base hours apply year-round"

CLOSED = "0" * HOURS
OPEN_247 = "1" * HOURS


@dataclass(frozen=True)
class Hours:
    summer: str | None
    winter: str | None
    confidence: str  # high | medium | low | none
    flags: frozenset[str] = field(default_factory=frozenset)

    @property
    def parsed(self) -> bool:
        return self.confidence != "none"


NONE = Hours(None, None, "none")


# ---------------------------------------------------------------------------
# OSM opening_hours
# ---------------------------------------------------------------------------
def _osm_mask(oh: OpeningHours, week_start: datetime) -> tuple[str, bool]:
    bits, unknown = [], False
    for h in range(HOURS):
        state, _ = oh.state(week_start + timedelta(hours=h, minutes=30))
        bits.append("1" if state == State.OPEN else "0")
        unknown |= state == State.UNKNOWN
    return "".join(bits), unknown


def parse_osm(text: str | None) -> Hours:
    if not text or not text.strip():
        return NONE
    try:
        oh = OpeningHours(text.strip(), coords=NYC_COORDS, country="US")
    except (ParserError, ValueError):
        return Hours(None, None, "none", frozenset({"unparseable"}))
    summer, u1 = _osm_mask(oh, SUMMER_WEEK)
    winter, u2 = _osm_mask(oh, WINTER_WEEK)
    flags = {"unknown_state"} if (u1 or u2) else set()
    if re.search(r"sunset|sunrise|dusk|dawn", text):
        flags.add("solar")
    return Hours(summer, winter, "medium" if "unknown_state" in flags else "high", frozenset(flags))


# ---------------------------------------------------------------------------
# NYC free text
# ---------------------------------------------------------------------------
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DAY_RE = (
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tues|tue|wed|thurs|thur|thu|fri|sat|sun)s?\b\.?"
)
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]
_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?"
_RANGE = re.compile(
    rf"(?:{_TIME}|(dawn|sunrise))\s*(?:-|to|until)\s*(?:{_TIME}(?:\s*/\s*(dusk|sunset))?|(dusk|sunset))"
)


def _day_index(tok: str) -> int:
    tok = tok.strip(". ").lower()
    for i, d in enumerate(DAYS):
        if d.startswith(tok[:3]):
            return i
    raise ValueError(tok)


def _normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ")
    t = re.sub(r"a\.\s?m\.?", "am", t)
    t = re.sub(r"p\.\s?m\.?", "pm", t)
    t = re.sub(r"\b12\s*noon\b|\bnoon\b", "12pm", t)
    t = re.sub(r"\bmidnight\b", "12am", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _to_min(h: str, m: str | None, mer: str | None) -> int:
    hh, mm = int(h), int(m or 0)
    if mer == "pm" and hh != 12:
        hh += 12
    if mer == "am" and hh == 12:
        hh = 0
    return hh * 60 + mm


@dataclass
class _Range:
    start: int  # minutes since midnight
    end: int  # may be <= start for overnight
    start_pm_explicit: bool = False
    flags: set[str] = field(default_factory=set)


def _parse_range(m: re.Match, season: str) -> _Range:
    h1, m1, mer1, dawn, h2, m2, mer2, slash_dusk, dusk = m.groups()
    flags: set[str] = set()
    if dawn:
        start, mer1 = 6 * 60, "am"
        flags.add("dawn")
    else:
        if mer1 is None:
            # "9 - 4:30pm": a bare start hour is morning unless that would be absurd.
            mer1 = "am" if 5 <= int(h1) <= 11 else (mer2 or "am")
            if int(h1) == 12:
                mer1 = "pm"
        start = _to_min(h1, m1, mer1)
    if dusk:
        end = DUSK_MINUTES[season]
        flags.add("dusk")
    else:
        if mer2 is None:
            mer2 = "pm" if (mer1 == "am" and int(h2) <= 11) or int(h2) == 12 else (mer1 or "pm")
        end = _to_min(h2, m2, mer2)
        if slash_dusk:  # "8:30pm/dusk" -> whichever comes first
            end = min(end, DUSK_MINUTES[season])
            flags.add("dusk")
    return _Range(start, end, start_pm_explicit=(m.group(3) == "pm"), flags=flags)


def _paint(mask: list[str], day: int, r: _Range, value: str = "1") -> None:
    end = r.end if r.end > r.start else r.end + 24 * 60  # overnight wraps
    for h in range(24 * 2):
        mid = h * 60 + 30
        if r.start <= mid < end:
            mask[(day * 24 + h) % HOURS] = value


def _days_in(spec: str) -> list[int] | None:
    """Day selector text -> list of weekday indexes; None if no day mentioned."""
    s = spec.strip().lower()
    if re.search(r"daily|every ?day|7 days|all week", s):
        return list(range(7))
    if re.search(r"\bwee?k?\s?days\b", s):  # incl. the "weedays" typo seen in the data
        return list(range(5))
    if "weekend" in s:
        return [5, 6]
    if re.search(r"\bm\s*-\s*f\b", s):  # single-letter codes: only unambiguous ones
        return list(range(5))
    if re.search(r"\bs\s*-\s*s\b", s):
        return [5, 6]
    days: set[int] = set()
    rng = re.compile(rf"({_DAY_RE})\s*(?:-|to|through|thru)\s*({_DAY_RE})")
    for m in rng.finditer(s):
        a, b = _day_index(m.group(1)), _day_index(m.group(2))
        days |= {(a + i) % 7 for i in range((b - a) % 7 + 1)}
    days |= {_day_index(d) for d in re.findall(_DAY_RE, rng.sub(" ", s))}
    return sorted(days) or None


_LETTER_DAYS = re.compile(r"\b[mtwrfs]\s*-\s*[mtwrfs]\b")


def _season_of(label: str) -> set[str]:
    """Season label ('march-october', 'winter', 'fall, spring summer') -> reference seasons."""
    s = label.lower()
    out: set[str] = set()
    if re.search(r"summer|spring|fall|autumn", s):
        out.add("summer")
    if "winter" in s:
        out.add("winter")
    m = re.search(r"([a-z]{3})[a-z]*\s*(?:-|to|through)\s*([a-z]{3})[a-z]*", s)
    if m and m.group(1) in _MONTHS and m.group(2) in _MONTHS:
        a, b = _MONTHS.index(m.group(1)), _MONTHS.index(m.group(2))
        months = {(a + i) % 12 for i in range((b - a) % 12 + 1)}
        if 6 in months:  # July
            out.add("summer")
        if 0 in months:  # January
            out.add("winter")
    return out


_SEASON_SPLIT = re.compile(
    r"((?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*(?:-|to|through)\s*"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)"
    r"|(?:(?:fall|spring|summer|autumn|winter)"
    r"(?:[ ,]+(?:and\s+)?(?:fall|spring|summer|autumn|winter))*))"
    r"\s*:"
)


def _fix_pm_typos(per_day: dict[int, _Range]) -> bool:
    """'Tuesday: 10:00 pm - 6:00 pm' -> 10 am when the am reading matches other days."""
    fixed = False
    starts = [r.start for r in per_day.values()]
    for r in per_day.values():
        if r.start_pm_explicit and r.end < r.start and r.end >= 12 * 60:
            am = r.start - 12 * 60
            if starts.count(am) >= 1:
                r.start = am
                r.flags.add("typo_fixed")
                fixed = True
    return fixed


def _parse_body(t: str, season: str) -> tuple[str | None, set[str], bool]:
    """Parse one season's text. Returns (mask, flags, leftover_digits)."""
    flags: set[str] = set()
    mask = ["0"] * HOURS
    any_range = False

    if re.search(r"24 ?hours|24/7|open 24", t):
        return OPEN_247, flags, False

    # Per-day lines: "monday: 10:00 am - 6:00 pm" / "sunday\tclosed"
    lines = [ln.strip() for ln in re.split(r"[\n;]", t) if ln.strip()]
    per_day: dict[int, _Range] = {}
    closed_days: set[int] = set()
    day_lines = 0
    for ln in lines:
        m = re.match(rf"^({_DAY_RE})\s*[:\t ]\s*(.*)$", ln)
        if not m:
            continue
        day_lines += 1
        d, rest = _day_index(m.group(1)), m.group(2)
        if re.match(r"^cl(osed)?\b", rest.strip()):
            closed_days.add(d)
            continue
        rm = _RANGE.search(rest)
        if rm:
            per_day[d] = _parse_range(rm, season)
    if day_lines >= 3:
        if _fix_pm_typos(per_day):
            flags.add("typo_fixed")
        for d, r in per_day.items():
            flags |= r.flags
            _paint(mask, d, r)
        any_range = bool(per_day)
        leftover = len(per_day) + len(closed_days) < 7
        return ("".join(mask) if any_range else None), flags, leftover

    # Free-form: segments of "<day selector> <time range>", e.g.
    # "monday to friday 9:00 am to 8:00 pm, saturday 10:00 am to 8:00 pm"
    matches = list(_RANGE.finditer(t))
    if not matches:
        return None, flags, bool(re.search(r"\d", t))
    painted = [0] * 7
    pos = 0
    for rm in matches:
        selector = t[pos : rm.start()]
        days = _days_in(selector)
        if days is None and _LETTER_DAYS.search(selector):
            flags.add("ambiguous_days")  # e.g. "M-T": Mon-Tue or Mon-Thu?
        if days is None and len(matches) == 1:
            # selector after the range: "10 am to 5 pm on weekdays"
            days = _days_in(t[rm.end() :])
        if days is None:
            days = list(range(7))
        r = _parse_range(rm, season)
        flags |= r.flags
        for d in days:
            _paint(mask, d, r)
            painted[d] += 1
        any_range = True
        pos = rm.end()
    # Two unlabeled ranges covering the same day ("6am-12am, 8am-10pm",
    # "... (indoor season) ... (outdoor season)") -> we took the union; flag it.
    closure = re.search(r"clos(?:ed|ure|ing)[^.]*?(?:from|between)\s+", t)
    if max(painted) > 1 and not closure:
        flags.add("ambiguous_ranges")

    # "with a one-hour closure for cleaning from 12pm-1pm" -> carve out
    cm = re.search(r"clos(?:ed|ure|ing)[^.]*?(?:from|between)\s+", t)
    if cm:
        rm = _RANGE.search(t, cm.end())
        if rm:
            r = _parse_range(rm, season)
            # undo: the closure range was painted as open above; paint it closed
            for d in range(7):
                _paint(mask, d, r, "0")
            flags.add("midday_closure")
    tail = t[pos:]
    leftover = bool(re.search(r"\d", tail)) and not cm
    return "".join(mask), flags, leftover


def parse_nyc(text: str | None) -> Hours:
    if text is None or not str(text).strip():
        return NONE
    t = _normalize(str(text))
    flags: set[str] = set()

    if re.fullmatch(r"\s*(temp(orarily)?\.? )?closed\.?\s*", t):
        return Hours(CLOSED, CLOSED, "high", frozenset({"closed"}))
    if "by permit" in t:
        return Hours(None, None, "none", frozenset({"by_permit"}))
    if "open later seasonally" in t or "later in season" in t:
        flags.add("season_extension_unknown")
        t = re.sub(r",?\s*open later seasonally\.?", "", t)

    # Season-specific blocks: "march-october: 7am - 11pm, november-march: 7am - 10pm"
    parts = list(_SEASON_SPLIT.finditer(t))
    masks: dict[str, str | None] = {}
    leftover = False
    if parts:
        flags.add("seasonal_text")
        for i, sm in enumerate(parts):
            body = t[sm.end() : parts[i + 1].start() if i + 1 < len(parts) else len(t)]
            for season in _season_of(sm.group(1)):
                mask, f, lo = _parse_body(body, season)
                masks[season] = mask
                flags |= f
                leftover |= lo
        # a season not covered by any block -> unknown for that season
        summer, winter = masks.get("summer"), masks.get("winter")
        if summer is None or winter is None:
            flags.add("season_missing")
    else:
        summer, f1, lo1 = _parse_body(t, "summer")
        winter, f2, lo2 = _parse_body(t, "winter")
        flags |= f1 | f2
        leftover = lo1 or lo2

    if summer is None and winter is None:
        return Hours(None, None, "none", frozenset(flags | {"unparseable"}))
    if leftover:
        conf = "low"
        flags.add("partial")
    elif flags - {"seasonal_text"}:
        conf = "medium"
    else:
        conf = "high"
    return Hours(summer, winter, conf, frozenset(flags))


def hours_open(mask: str | None) -> int:
    return mask.count("1") if mask else 0
