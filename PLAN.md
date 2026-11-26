# NYC Restrooms — project plan

Working name: **nyc-restrooms** (rename later). Three parts, built in phases; stop after each phase for review.

1. **Restroom deserts** — where in NYC are you far from a free, open restroom, at what hours, and how many people does that hit?
2. **Restroom-likelihood model** — for every place in the city (cafés, shops, hotels, malls...), how likely is it to have a restroom you can use, and on what terms?
3. **Delivery-worker mode** — every NYC food pickup spot where app delivery workers are likely legally entitled to a bathroom, plus their rights and how to report a denial.

---

## What the data checks found (2026-11-26)

| Source | What it gives | Size / quality |
|---|---|---|
| NYC Open Data `i7jb-7jku` Public Restrooms | Official restrooms: type, status, hours, accessibility, changing stations, menstrual-friendly | 1,100 rows (998 operational). 821 parks, 218 libraries, 25 plazas, 15 POPS, 13 transit. Hours are **free text**, 1,010/1,100 filled. Updated Nov 2026 |
| Parks Inspection Program (`9byw-znpj`, `mp8v-wjtf`, `xmiz-qy72`, `r8mb-budb`, `yp6n-7jdy`) | Cleanliness / condition / hazard ratings for Parks restrooms | Updated Nov 2026. Free condition layer |
| OpenStreetMap (NYC relation 175905) | `amenity=toilets` standalone: 796. Places tagged `toilets=*`: ~1,350 (1,070 yes, 248 no, ~25 customers). `toilets:access`: 129 customers, 66 permissive | ~17.3k food places + ~25.9k shops in NYC → **only ~3% labeled**, and labels skew "yes" (restaurants 333 yes / 18 no, bars 173 / 0). Selection bias: mappers tag what they notice |
| DOHMH Restaurant Inspections `43nn-pn8j` | Every food service establishment, address, cuisine, coordinates | 31,518 distinct establishments. The universe for delivery-worker mode |
| Refuge Restrooms API | Gender-neutral / accessible restrooms, crowdsourced | Dense in Midtown (100 within 0.6 mi of Times Sq) but mostly entered 2014–2019 → weak, stale labels |
| 311 Service Requests `erm2-nwe9` | — | **No** complaint type for delivery-worker bathroom denial. Only "Restroom Non-Compliance With LL 79/16" (185 rows, unrelated) |
| Google Places API (New) `restroom` field | Exists (Enterprise + Atmosphere tier) | **Not used.** Google's Places policy allows storing only `place_id` (indefinitely) and lat/lng (30 days); bans storing content and "creating content based on Google Maps Content." That rules out training labels and a stored map layer. Decision: build on open data only |

### Delivery-worker law: what it actually says (DCWP pages, read 2026-11-26)
- Effective Jan 24, 2022. Mechanism: apps must have a written agreement with each restaurant they list, and **the agreement must include bathroom access** for delivery workers picking up orders. Restaurants must comply with those agreements.
- DCWP FAQ: "Workers must be allowed to use the bathroom at most pickup locations." "Restaurant" = all food service establishments (restaurants, food halls, carts, stands, trucks).
- Exceptions: "limited exceptions for health or safety reasons" — not defined. Pages don't say whether a restaurant with no customer bathroom must provide one.
- Penalty: workers denied access "may be entitled to $200 per instance." Complaints: DCWP online (nyc.gov/workers) or 311 → ask for DCWP. 2-year window. Multilingual bathroom-access card at nyc.gov/DeliveryApps.
- Jan 2026: Local Laws 123/124 "improve bathroom access for contracted delivery workers" (and extend pay rules to grocery delivery). Exact bathroom text is in Legistar; read before Phase 4.
- **No public list** of which restaurants are on apps, and **no public complaint/violation data**.
- → The app can say "**likely covered**" (food service establishment in the DOHMH data, likely on apps), never "must let you in." Violation data has to be crowdsourced.

---

## Phase 0 — Setup (half a day)
- New repo `~/nyc-restrooms` (Python 3.13 venv, `src/` layout, pytest, ruff, GitHub Actions CI).
- `config/sources.py`: data registry. **Every dataset ID gets a live check before it goes in** (transit-pulse lesson: dead IDs). Still to verify: MTA hourly subway ridership, DOT bi-annual pedestrian counts, NYC building footprints, NYC Tourism/landmark POIs.
- Bulk OSM via the **Geofabrik New York extract + pyosmium**, not Overpass (public Overpass was overloaded during the check; keep Overpass for small queries only).

**Done when:** `make ingest` dry-run hits every source and CI is green.

## Phase 1 — Data layer (≈1 week)
- Ingest + cache (parquet; never pyarrow in a TF process, but this project doesn't need TF): official restrooms, Parks inspections, OSM POIs with all `toilets*` / `wheelchair` / `changing_table` / `opening_hours` tags, Refuge NYC, DOHMH establishments (deduped by CAMIS, latest inspection).
- **Hours parser**: (a) OSM `opening_hours` via an existing parser; (b) NYC free text ("Monday\t9 am - 8 pm…", "8am-4pm, Open later seasonally", "dawn to dusk") → weekly 168-hour open mask + a `hours_confidence` flag. Test suite built from real strings in the dataset; report % parsed.
- Unified `places` table: `place_id, source(s), name, category, lat, lon, restroom (known yes/no/unknown), access (public / customers / workers-legal / unknown), weekly_open_mask, accessible, changing_table, gender_neutral, condition_score, last_verified, source_date`.
- Entity matching across sources (OSM ↔ DOHMH ↔ NYC restrooms ↔ Refuge): name + distance, with a hand-checked match-rate audit (as in trendcatcher).

**Done when:** one table, tests green, parse rate and match rate reported.

## Phase 2 — Restroom deserts (≈1 week) — first public result
- Walk network: OSMnx pedestrian graph for the five boroughs.
- Grid: H3 resolution 9 hexes (~0.1 km²).
- Per hex, per hour of the week: walking minutes to the nearest restroom that is **free, public, and open at that hour** (official + OSM `access=public/yes`). Second tier: "with a customer purchase."
- Demand weights: MTA hourly station ridership, DOT pedestrian counts, landmark/tourist POIs → people-minutes stranded.
- Outputs: interactive map (hour slider), "worst 20 deserts by people affected," day vs night comparison, borough equity breakdown, Parks condition overlay.
- Pre-register before computing: the headline metric (share of weekday foot traffic more than 10 walking min from a free open restroom, 9am vs 11pm) and how it's calculated.

**Done when:** map + findings write-up, numbers reproducible from one command.

## Phase 3 — Restroom-likelihood model (≈1.5 weeks)
- **Target**: access tier per place: `public` / `customers-only` / `none`. Two-stage if needed (has restroom → access terms). Having a restroom is nearly settled by category for restaurants and bars; access is the useful question.
- **Baseline to beat**: per-category base rate (smoothed) from OSM labels.
- **Features**: OSM category, chain/brand (`brand` tag + name normalization; chain policies are known, e.g. "customers only"), building footprint area, opening-hours length, inside a mall/station/hotel, neighborhood, distance to tourist POIs, DOHMH presence (= food service establishment).
- **Test set: a hand audit**, not OSM labels (same selection bias). ~200 places, stratified by category and borough, randomly sampled *before* checking. Checked by visiting or calling: has restroom? Free to walk in / customers only / no?
- **Pre-registered pass rule** (written and committed before the audit is scored): model beats the category baseline on log-loss with a bootstrap 95% CI excluding zero, and calibration error ≤ baseline. **If it fails, publish that it failed** (as nsefactor / volleycheck did), and the map falls back to category rates.
- Output: probability + access tier for all ~43k places, shown as "likely / possible / unlikely" with an honest confidence label.

**Done when:** pre-registration committed, audit scored once, result written up either way.

## Phase 4 — Delivery-worker mode (≈1 week)
- First read the Local Law 123/124 Legistar texts; update scope and wording.
- Layer: all ~31.5k DOHMH food service establishments as "likely covered pickup locations," with the caveat that it depends on the restaurant being on a delivery app.
- Rights panel: what the law says, $200 per denial, the DCWP complaint link, and the official multilingual card. Languages: English, Spanish, Mandarin, Bengali, French (matches the delivery workforce; reuse DCWP translations where possible).
- Worker reports: "let me in" / "refused" per restaurant. Anonymous: no accounts, no stored identity, rate-limited.
- **Publishing rule (defamation and safety)**: no single report goes public. Per-restaurant flags show only after N independent reports in a window; otherwise reports roll up to neighborhood-level "refusal rate." Restaurants can contest. Reports are not legal findings; say so.
- Optional outreach later: Los Deliveristas Unidos (workers' group) for feedback before a public launch.

**Done when:** layer + rights panel + report flow working locally, publishing rule enforced in code with tests.

## Phase 5 — App + reliability (≈1–1.5 weeks)
- Static PWA on GitHub Pages (same stack as hearsay / DrugSupply Watch): MapLibre + OSM tiles, "open now near me," filters (free, accessible, changing table, gender-neutral), worker mode toggle.
- Crowd confirmations ("still open," "free," "code changed," "clean/dirty"): small backend (Supabase or Cloudflare Worker + D1, decided at phase start).
- **Reliability decay**: each listing's confidence decays without fresh confirmation; official data and confirmations push it back up (RentCast lesson: most listings go stale).
- Nightly GitHub Actions refresh of the open datasets.

**Done when:** live URL, nightly refresh green, works on a phone.

---

## Risks
- OSM labels are thin and biased → hand audit as test set; category baseline as the floor.
- Hours text is messy → parser with a confidence flag; low-confidence hours shown as "check hours."
- Legal wording → always "likely covered," link to DCWP, read Legistar before Phase 4.
- Crowd reports can be abused or defame → thresholds, aggregation, contest path.
- Google data not usable under its terms → open data only.

## Where you come in
- Hand audit for Phase 3: ~200 places, roughly two afternoons of walking plus phone calls. This is what makes the model result trustworthy.
- Review at the end of each phase.
