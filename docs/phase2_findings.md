# Phase 2 findings: NYC restroom deserts

Computed 2026-11-26/27 under the [pre-registration](phase2_prereg.md), which was pushed to GitHub at 2026-11-27 00:00:31 UTC, before any result existed. Raw numbers are in [`phase2_results.json`](phase2_results.json) and per station in [`phase2_station_table.csv`](phase2_station_table.csv). The interactive map is in [`map/`](map/index.html).

## Headline

**At 11 pm on a weekday, 85% of NYC subway entries happen at a station where no free public restroom with listed hours is open within a 10-minute walk.** At 9 am it's 14%. At 6 pm it's 25% or 7%, depending on how one ambiguous line in the city's data is read.

Share of weekday subway entries at stations more than a 10-minute walk from an open restroom (primary restroom set):

| | 09:00 | 18:00 | 23:00 |
|---|---|---|---|
| Summer, reading A (park restrooms close 4 pm) | **14.1%** | **25.4%** | **85.3%** |
| Summer, reading B (park restrooms close at dusk) | 14.1% | 7.5% | 85.3% |
| Winter (A = B) | 17.2% | 26.9% | 86.9% |

**Stated expectation: met.** The 23:00 share exceeds 09:00 by 71.3 points (summer) and 69.7 points (winter), against the expected ≥ 20.

**Where the ambiguity matters:** 613 of the 1,100 official restrooms (56%) list their hours as "8am-4pm, Open later seasonally". Whether "later" means dusk changes the summer 6 pm figure more than threefold (25.4% vs 7.5%). It has no effect at 9 am or 11 pm. The city could settle this by publishing actual seasonal closing times.

## How much the night number depends on missing data

The primary set uses only restrooms with listed hours: 1,087 official restrooms (including those closed by their status) plus 26 OpenStreetMap toilets. **542 more public OSM toilets have no hours at all**, and the night figure depends heavily on what you assume about them:

| Restroom set (summer, reading A) | 09:00 | 18:00 | 23:00 |
|---|---|---|---|
| **Primary** (pre-registered) | 14.1% | 25.4% | 85.3% |
| Exploratory: sensitivity minus OSM toilets within 150 m of an official restroom ¹ | 11.8% | 20.8% | 55.7% |
| Sensitivity bound (pre-registered): every unknown-hours toilet open 24/7 | 11.1% | 9.5% | 19.2% |

¹ *Not pre-registered; added after seeing the sensitivity result.* 343 of the 542 unknown-hours toilets sit within 150 m of an official restroom, and 219 are building outlines with NYC building IDs. They're most likely the same park comfort stations, which follow park hours. Treating them as open all night is implausible.

**The honest reading:** the real late-night share is probably between about 56% and 85%. The 19% bound needs hundreds of park comfort stations to be open 24/7, which they aren't. Either way, late night is when the city has the least restroom access, and the size of the gap is limited by data the city doesn't publish (hours for every comfort station).

Only **27 restrooms** in the primary set are open at 11 pm on a Wednesday: the Port Authority and GWB bus terminals, highway gas stations, a few Hudson River Park piers, the Brooklyn Army Terminal, and a handful of others.

## Through the day

Primary set, summer, share of entries more than 10 min from an open restroom, by hour (A = 4 pm close, B = dusk close; they differ only from 16:00 to 19:00):

| Hour | 0 | 3 | 6 | 7 | 8 | 9 | 12 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 89% | 99% | 91% | 68% | 15% | 14% | 7% | 5% | 17% | 17% | 25% | 36% | 47% | 52% | 69% | 85% |
| B | 89% | 99% | 91% | 68% | 15% | 14% | 7% | 5% | 5% | 5% | 7% | 9% | 47% | 52% | 69% | 85% |

The best-served hours are midday (5–7%), when both parks and libraries are open. Coverage falls apart from 8 pm on.

## Threshold sensitivity (summer, reading A)

| Walk limit | 09:00 | 18:00 | 23:00 |
|---|---|---|---|
| 5 min | 62.9% | 59.7% | 99.5% |
| 10 min | 14.1% | 25.4% | 85.3% |
| 15 min | 2.7% | 12.6% | 67.7% |

## By borough (summer, reading A)

| Borough | 09:00 | 18:00 | 23:00 |
|---|---|---|---|
| Manhattan | 6.4% | 9.9% | 79.4% |
| Bronx | 14.5% | 58.8% | 95.1% |
| Brooklyn | 20.2% | 63.2% | 98.8% |
| Queens | 24.2% | 62.6% | 100.0% |

By evening, the outer boroughs are far worse than Manhattan: about 60% vs 10% at 6 pm under reading A. Under reading B, the gap narrows to roughly 12–22% vs 2%. **Staten Island contributes nothing to the subway figure.** Its only station in the data, St George (SIR), is recorded under subway mode but has zero subway-mode entries in both windows. The rest of the Staten Island Railway reports under 2 station IDs outside subway mode. Staten Island appears on the hex map only.

## Stations where riders are most often stranded

"Stranded entries" means weekday entries made when no free open restroom is within 10 minutes (summer, A). **65 of 425 stations have no qualifying restroom within 10 minutes at any weekday hour.** Across the system, about 1.16 M of 4.02 M weekday entries (29%) happen while stranded.

| Station | Weekday entries | Stranded | Share | Walk 9 am / 6 pm / 11 pm (min) |
|---|---|---|---|---|
| Canal St (6,J,Z,N,Q,R,W) | 36,862 | 23,417 | 64% | 5 / 11 / 21 |
| Jackson Hts-Roosevelt Av | 45,543 | 22,718 | 50% | 7 / 13 / 58 |
| Crown Hts-Utica Av (3,4) | 16,478 | 16,478 | 100% | 10 / 38 / 90 |
| Flushing-Main St (7) | 45,253 | 15,476 | 34% | 8 / 4 / 47 |
| Bedford Av (L) | 27,907 | 14,953 | 54% | 8 / 10 / 11 |
| 14 St/6 Av | 34,345 | 13,916 | 40% | 11 / 6 / 17 |
| 90 St-Elmhurst Av (7) | 13,187 | 13,187 | 100% | 12 / 16 / 41 |
| Jamaica-179 St (F) | 13,052 | 13,052 | 100% | 17 / 18 / 31 |
| W 4 St-Wash Sq | 36,744 | 12,510 | 34% | 4 / 5 / 13 |
| 36 St (D,N,R), Brooklyn | 12,235 | 12,235 | 100% | 15 / 17 / 18 |

Full top 20 in `phase2_results.json`, all stations in the CSV.

## "With a purchase" (secondary, lower bound)

Adding places known to have a customer restroom (OSM tags or Refuge) with listed hours: 9 am 8.3%, 6 pm 6.4%, 11 pm 21.8% (summer, A). Paying for access helps most at night. This is a **lower bound** on what a customer could use, because most businesses have no restroom data. Predicting it is Phase 3's job.

## Condition of park restrooms (overlay)

The Parks inspection data can't be tied to an individual restroom: its `csnumber` is a 1–3 ordinal within each inspection, not a comfort-station ID. It *can* be tied to a park property. For the 550 official Parks restrooms in a property with exactly one comfort station, the property's latest restroom rating is that restroom's rating: **361 acceptable, 71 unacceptable, 114 not rated**, and 4 with no inspection on record (median inspection July 2026). The other 271 are left blank rather than guessed: 242 sit in parks with several comfort stations, and 29 fall outside any mapped park property. Per-restroom table: [`phase2_park_condition.csv`](phase2_park_condition.csv).

## Method checks
- **Walking network**: 1.25 M nodes from the OSM extract. Detour ratio (network ÷ straight-line, 1,998 random pairs 1–5 km apart): median 1.21, 90th percentile 1.47. The 1.2% above 3× are water crossings with no walkable bridge (Throgs Neck/Whitestone, the East River at Astoria). The Brooklyn, Manhattan, Williamsburg and Queensboro bridge walkways all connect. Staten Island is its own component (no walkway on the Verrazzano), as it should be. Details in [`phase2_walk_graph.json`](phase2_walk_graph.json), regenerated by `restrooms walk-graph`.
- **Ridership**: weekday 8 am averages 373k entries vs 72k on Sunday 8 am, confirming the weekday mapping. About 4.0 M weekday entries a day.
- **A bug found and fixed during Phase 2**: in OSM `opening_hours`, ", " separates whole rules, so "Mo, We, Fr 10:00-18:00" parsed as *open all day* Monday and Wednesday. 5% of NYC hours strings are written this way. It was found when a library showed as open at 11 pm. They're now parsed as weekday lists and flagged. The headline moved by 0.1 points.

## Deviations from the pre-registration
1. **OSM hours parsing fix** (made after the pre-registration, before the final run): weekday lists written "Mo, We, Fr" were being parsed as separate all-day rules (5% of OSM hours strings). Fixed and flagged `weekday_comma_fixed`. The headline moved by ≤ 0.1 points (summer 18:00 25.3% → 25.4%; 23:00 85.3% → 85.3%).
2. **Exploratory restroom set**: the "sensitivity minus OSM toilets within 150 m of an official restroom" variant, and its 150 m cutoff, were chosen *after* seeing the sensitivity result. It's reported as exploratory only.
3. **Map scope**: the pre-registration describes the hex map "for each hour of the week". The published map shows the 24 hours of one weekday (Wednesday) per scenario, to keep the page small. All 168 hours are computed and saved (`data/processed/hex_minutes_*.npy`).
4. **Weekday-encoding check**: first run by hand during the analysis (it passed). It's now an assertion in the ridership code (`check_weekday_encoding`). A test showed the first version of that assertion couldn't catch a one-day shift, so it was tightened to require both weekend slots to be below Tue–Thu.
5. **Parks condition overlay**: the pre-registration expected either a clean join or none. The keys don't join per restroom. A property-level join for single-station parks was used instead and is described above.

## Limits
- Subway **entries** stand in for where people are. Exits, pedestrians, tourists on foot, and bus riders aren't counted.
- "Open" means *listed* hours. Restrooms that are locked, broken or closed for cleaning outside their listed schedule aren't captured (the condition overlay covers part of this).
- Walking speed is fixed at 1.25 m/s, with no stairs, signal waits or accessibility penalties.
- One reference week per season, no holidays, Wednesday for the map.
