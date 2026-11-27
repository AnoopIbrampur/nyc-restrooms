# Phase 1 report: data layer

Built 2026-11-26 from sources fetched the same day (versions in [`data_manifest.json`](data_manifest.json); raw numbers in [`phase1_build.json`](phase1_build.json)).

**Output:** `data/processed/places.parquet` has **80,656 places** across the five boroughs. Each row carries its restroom evidence from every source in separate columns (`osm_*`, `official_*`, `refuge_*`), a `likely_covered_pickup` flag for delivery-worker mode, and summer/winter hourly open masks.

Reproduce:
```bash
make setup
uv run restrooms ingest     # ~520 MB, mostly the OSM extract
uv run restrooms build      # ~35 s
```

## 1. Sources

| Source | Raw | Kept | Notes |
|---|---|---|---|
| NYC Public Restrooms | 1,100 | 1,100 | 998 operational; 102 not operational / closed |
| OSM NY State extract | 499 MB | 62,593 venues in NYC | after dropping 213,383 non-venues (below) |
| DOHMH restaurants | 31,556 establishments | 30,748 | 808 have no coordinates; 3,881 not yet inspected (new permits) |
| Refuge Restrooms | 1,466 | 1,098 | 116 spam, 252 outside NYC |
| Parks inspection tables, MTA stations, DOT ped counts, boroughs | downloaded raw | — | used in Phase 2 |

DOHMH covers only restaurants and college cafeterias with an **active** permit (per the dataset description), so it needs no staleness flag. Food carts and trucks are not in it.

### OSM extraction check
The pyosmium extract clipped to borough land polygons, compared with the Overpass counts taken for the NYC admin area on 2026-11-26:

| | Overpass | Ours |
|---|---|---|
| `amenity=toilets` | 796 | 796 |
| any `toilets=*` | 1,351 | 1,350 |
| `toilets=yes` / `no` | 1,070 / 248 | 1,069 / 248 |
| food places | 17,322 | 17,313 |
| shops | 25,942 | 25,933 |

All within 0.1%. The small gap is water inside the admin area.

**Relations are skipped**: 4,165 statewide, mostly parking (1,176), nature reserves (964), park outlines (448) and tracks. Only a few dozen statewide are venues (39 hotels, 14 restaurants). City parks are covered by the official restrooms data.

### Venue filter
OSM tags street furniture with the same keys as venues. Without a filter, Staten Island alone had 122k "places" (82k parking spaces, 25k private backyard pools). Dropped: parking, benches, bike racks, trash cans, post boxes, private pools and gardens, sports pitches, schools and so on (full list in `build.py: NON_VENUE`). **Anything carrying a `toilets*` tag is always kept**, as is every `amenity=toilets`.

Result by borough: Manhattan 27,068 · Brooklyn 23,000 · Queens 19,631 · Staten Island 5,643 · Bronx 5,304 · 10 outside the borough polygons (shoreline).

### Refuge spam
116 entries from an Aug–Dec 2015 wave have personal first names and random-letter "street" values (`xMUBmLhTsAKaAZMiIk`). All are marked `approved` by the API. They're detected by pattern (`build.py: refuge_spam`) and dropped. The rest is still mostly 2014–2019 data and stays a weak, stale label.

## 2. Hours

Masks are 168 hours (Mon 00:00 first). An hour counts as open if the place is open at h:30. Two reference weeks, both free of US holidays: **summer = week of 2026-07-13, winter = week of 2027-01-25**.

### Official restrooms (free text): confidence by row
| Confidence | Rows | Meaning |
|---|---|---|
| high | 335 | parsed, no assumptions |
| medium | 667 | parsed, with a named assumption (flags below) |
| low | 1 | only part understood |
| none | 97 | 90 have no hours at all; the rest are "Open by permit", a URL, "Open during games…" |

The medium count is dominated by **one string covering 613 rows (56%)**: "8am-4pm, Open later seasonally". We do **not** invent the later closing time. Those rows keep 8am–4pm in both seasons and carry `season_extension_unknown`. **Phase 2 must report its desert numbers under both readings (4pm close vs dusk close)**, because this one assumption changes the late-afternoon picture. *(Corrected in Phase 2: an earlier version said it drove the 9am-vs-night comparison. It doesn't. Both readings agree at 9am and 11pm and differ only between 16:00 and 20:00 in summer.)*

Other flags (rows): `seasonal_closed_winter` 126 (the dataset marks them Seasonal, so they're closed in the winter week), `not_operational` 102 (closed in both weeks), `typo_fixed` 27, `dusk` 17, `ambiguous_ranges` 5, `midday_closure` 5.

**The official status and season fields override hours from any source.** When an official restroom is matched to a library or park with OSM `opening_hours`, the venue's hours are used only if the restroom is operational, and seasonal restrooms are still closed in winter (`build.py: apply_official_status`, tested). Matched official restrooms also keep their **own coordinates and name**, not the park centroid or an unnamed OSM toilet node, because Phase 2 measures walking time to the restroom itself.

- **Typo rule** (`typo_fixed`): "Tuesday: 10:00 pm - 6:00 pm" is read as 10 am only when the end is before the start, both are pm, and another day starts at exactly the am time. Otherwise it's left alone (tested).
- **Dusk**: 20:00 summer, 17:00 winter, rounded *down* from actual sunset so a mask never claims a restroom is open after it closes.
- **Ambiguous text**: unlabeled double ranges ("6am - 12am, 8am - 10pm", "(indoor season)… (outdoor season)") and letter codes like "M-T" are unioned and flagged, never reported as high confidence.

### OSM `opening_hours`
21,254 places carry the tag. 20,992 are parsed with opening-hours-py (99.6%), using NYC coordinates for sunrise/sunset and `country=US` for `PH`.

**Coverage gap:** 58,661 places (73%) have no hours from any source. Phase 2's "open now" layer can only use the 22k that do. Everything else is "hours unknown".

## 3. Cross-source matching

One-to-one greedy assignment over candidates within a radius (`match.py`). Rules (`build.py`):

- **Official ↔ OSM** (100 m): unnamed OSM toilets by distance (≤ 60 m). Official libraries match only OSM libraries: any name within 40 m (OSM often says just "Brooklyn Public Library"), else name similarity ≥ 85. Parks match park-like OSM features at similarity ≥ 70 within 60 m. Everything else needs ≥ 85.
- **DOHMH ↔ OSM** (75 m): similarity ≥ 85, or the same house number with similarity ≥ 65.
- **Refuge ↔ OSM, then ↔ unmatched DOHMH** (75 m): similarity ≥ 80, or the same house number with similarity ≥ 65.

Links: official↔OSM 901 of 1,100 · DOHMH↔OSM 13,505 of 30,748 · Refuge↔OSM 441, Refuge↔DOHMH 36.

### Audit
Two rounds, each a seeded random sample of 40 accepted matches plus 20 near-misses per link. Near-misses are drawn from the most name-similar unmatched pairs, the cases most likely to be missed matches.

- **Round 1** (seed 20261126) found the problems and drove the rule changes. Accepted matches were 117/120 correct. Near-misses were the real issue: 9/20 official, ~12/20 DOHMH and 5/20 Refuge were actual matches (generic library names, "17" vs "17th", store numbers like "#34102").
- **Round 2** (seed 20261127, no tuning afterwards) is the reported result. Verdicts and notes are in [`match_audit.csv`](match_audit.csv). It is **not fully independent of round 1**: near-misses come from the same fixed pool (the most name-similar unmatched pairs), and a few accepted matches recur. Pairs seen in both rounds include Pier 6, Buddha Bar, Kennedy Fried Chicken, Cornbread, "Chitpotle" and Champs Diner.

| Link | Accepted matches correct | Hard near-misses that were real |
|---|---|---|
| Official ↔ OSM | 39/40 | 4/20 |
| DOHMH ↔ OSM | 40/40 | 7/20 |
| Refuge ↔ OSM | 38/40 | 2/20 |
| **All** | **157/160 (98%)** | 13/60 |

**Precision is high, and the misses sit in a thin band.** The 13 real near-misses are spelling and spacing variants ("Mudville9"/"Mudville 9", "Buddha"/"Bhudda"), recreation facilities with different names, and house numbers a couple apart. They come from the ~100 most similar unmatched pairs per link, so the absolute number missed is in the tens per link, small next to 13.5k DOHMH matches. I did not estimate recall over the full unmatched set. The three wrong matches are a business that replaced another at the same address, a café inside Grand Central matched to the terminal, and two different features on Pier 6.

*Audit caveat: the verdicts are my judgment from names, addresses and distances, not field visits.*

## 4. Labels in the places table (kept separate on purpose)

| Column | Values |
|---|---|
| `osm_toilets` | yes 1,069 · no 248 · customers 30 · junk 3 |
| `osm_toilets_access` | customers 136 · permissive 67 · yes 15 · public 15 · private 2 · no 1 |
| `official_present` | 1,100 |
| `refuge_present` | 1,098 |
| `likely_covered_pickup` | 30,748 (DOHMH food service establishments; a legal attribute, not a restroom observation) |

3,406 places have restroom evidence of any kind. That's 4% of the table, which is why Phase 3 needs its own hand audit as the test set.

## 5. Carried into later phases
- **Phase 2**: report deserts under both "open later seasonally" readings. Join the Parks condition data (confirm that `csnumber` and `cs_id` are the same key first). Treat 73% of places as hours unknown.
- **Phase 3**: OSM labels skew "yes" (restaurants 333 yes vs 18 no in the earlier Overpass check). Access labels are sparse (~230). Test on a stratified hand audit, not OSM labels. **Category is inconsistent across sources**: 17,243 restaurants found only in DOHMH have `category = dohmh_restaurant`, while matched ones carry OSM categories (`amenity=restaurant`, `amenity=cafe`, ...). Harmonize them, for example by mapping DOHMH cuisine to OSM-style classes, before using category as a feature or as the baseline's grouping.
- **Phase 4**: `likely_covered_pickup` excludes 808 restaurants without coordinates and all food carts and trucks. 3,881 have never been inspected and may not be open yet.
