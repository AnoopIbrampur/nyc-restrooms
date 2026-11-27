# Phase 2 pre-registration: restroom deserts

Written 2026-11-26, **before any walk times or results were computed**, and committed on its own. (The commit is local until pushed, so its timestamp is not independent proof. It records intent.)

## Question
How many NYC subway riders enter at a station where the nearest **free, public restroom that is open at that hour** is more than a 10-minute walk away? How does that change across the day and between seasons?

## Headline metric (H)
**Share of weekday subway entries at stations whose network walking time to the nearest open restroom in the primary set is more than 10 minutes.**

Reported for each cell of:
- **Hour** (the hour starting at): 09:00, 18:00, 23:00, averaged over Monday–Friday
- **Season**: summer (hours mask: week of 2026-07-13; ridership: 2026-07-06 to 2026-08-02) and winter (hours mask: week of 2027-01-25; ridership: 2026-01-05 to 2026-02-01 excluding 2026-01-19, MLK Day)
- **Reading** of the 613 official restrooms whose hours say "8am-4pm, Open later seasonally":
  - **A**: closes 16:00 in both seasons
  - **B**: closes at dusk (20:00) in summer, 16:00 in winter

A and B can only differ between 16:00 and 20:00 in summer. At 09:00 and 23:00 they're identical by construction, so the 18:00 summer cell is where the assumption matters. Both readings are always reported, and neither is called "the" answer.

### Definitions fixed in advance
- **Primary restroom set**:
  - official NYC restrooms (Public Restrooms dataset) that are operational after the Phase 1 status override, with known hours, open at that hour. This includes the 13 transit restrooms: the MTA ones are listed as outside fare gates and open to the public, and the Port Authority ones are in public concourses.
  - plus OSM `amenity=toilets` that are **not** matched to an official restroom, whose `access` is not `private`/`no`/`customers`, whose `fee` is not `yes`, and whose `opening_hours` parsed and say open at that hour.
- **Walking**: shortest path on a pedestrian network built from the 2026-11-26 OSM extract. Excluded: motorways, trunk roads without `foot=yes`, `foot=no`, `access=private`/`no` without `foot=yes`, construction, proposed, raceway. Speed **1.25 m/s** (signal waits not modeled). The off-network snap distance at both ends is added at the same speed.
- **Threshold**: **10 minutes** (750 m including snap legs). A station that can't reach any open restroom on the network counts as more than 10 minutes.
- **Entries**: MTA Subway Hourly Ridership (`5wq4-mkjj`), `transit_mode = subway` only, summed over fare classes. Each hour-of-week cell is the mean over the distinct dates in the window for that weekday. Hourly data records **entries**, not exits or pedestrians.
- **Station location**: the ridership dataset's own station-complex coordinates.

### Not measured by H
- **Staten Island.** The Staten Island Railway reports ridership under only 2 station IDs for the whole line, so the borough isn't represented in H. It appears on the hex map only.
- Pedestrians who don't use the subway, tourists' walking routes, exits, and the quality or cleanliness of restrooms.

### Stated expectation (reported either way)
The 23:00 share will exceed the 09:00 share by at least 20 percentage points, in both seasons.

## Secondary outputs (descriptive, not tested)
1. **Sensitivity bound**: H recomputed counting OSM toilets with unknown hours, and the operational official restrooms with no hours, as always open. This gives the most favorable plausible reading.
2. **Threshold curve**: H at 5, 10 and 15 minutes.
3. **Hour profile**: H for all 24 weekday hours and both seasons, under readings A and B.
4. **Worst stations**: the top 20 stations by weekday "stranded entries", meaning the sum over hours of entries × 1[walk > 10 min]. Summer, reading A.
5. **Borough breakdown** of H (Manhattan, Brooklyn, Queens, Bronx).
6. **"With a purchase" tier**: H recomputed adding places known (from OSM tags or Refuge) to have a restroom available to customers, using their opening hours. This is labeled as a lower bound on what a paying customer could use, since predicting restrooms is Phase 3's job.
7. **Hex map** (H3 resolution 9, land only): walking minutes to the nearest open primary restroom, for each hour of the week and each season. Hexes whose centroid is more than 150 m from the network are marked "no network". **Hex area isn't people, so no headline number is computed from hex shares.**
8. **Condition overlay** (timeboxed): the latest Parks inspection rating for official Parks restrooms, if the Parks keys join cleanly. Otherwise it's omitted, with a note.

## Checks before trusting walk times
- **Detour ratio**: network distance ÷ straight-line distance for 2,000 random node pairs 1–5 km apart, within one component. Expect a median of about 1.2–1.4. A long tail above 3 means missing connections.
- **Bridges**: the Brooklyn Bridge and Manhattan Bridge walkways connect Manhattan and Brooklyn in the graph.
- **Component handling**: keep every connected component with at least 1,000 nodes, and snap only to those.
- **Weekday encoding**: SoQL's day of week has Sunday = 0. Assert that weekday 08:00 entries are much higher than Sunday 08:00 entries.
