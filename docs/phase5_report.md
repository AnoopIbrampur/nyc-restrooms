# Phase 5 report: app, reporting backend, nightly refresh

**Status (2026-11-27):** built and tested locally. Live now: the nightly data refresh and the shared data file the worker page uses. **Not live:** the API (needs a Cloudflare account and deploy approval) and the app page (`site_drafts/app/`, needs publish approval). With `apiBase` empty in `docs/config.js`, confirmation and report buttons stay off on the live site.

## What was built
### 1. Report publishing rule, one source of truth
- The rule now needs refusals from **3+ distinct device tokens and 3+ distinct network hashes**, since a browser token alone can be reset by clearing storage. Same-day ties are broken by submission order.
- It's written once as SQL (`backend/sql/public_places.sql`, `public_areas.sql`), which the server runs.
- `tests/test_sql_parity.py` runs that SQL in SQLite and checks it matches the Python reference (`restrooms.reports`) exactly on **300 randomized report sets**. A guard confirms the random cases actually list places and areas.
- `backend/rules.json` holds the thresholds, and a test checks they match the Python constants.

### 2. API (Cloudflare Worker + D1): `backend/`
- **Endpoints:** `GET /v1/public` (aggregates only), `POST /v1/report`, `POST /v1/confirm`, `POST /v1/dispute`.
- **Daily cron:** deletes reports after 180 days and confirmations after 90.
- **Stored:** keyed hashes (HMAC) of the device token and network address, plus the date. No free text, no names, no precise locations, no contact details. Cloudflare logs IPs under its own policy, and the privacy note says so.
- **Defenses:** Turnstile on every write (fails closed outside local dev), 40 writes per network per day, CORS limited to the Pages origin, and a dispute automatically withholds a listing.
- **Local smoke test** (`backend/smoke_test.py`, 10/10):
  - 2 refusals: not listed. A third from a new device and network: listed.
  - 3 devices on one network: not listed.
  - A dispute withholds the listing.
  - Bad inputs are rejected, and the rate limit triggers at the 41st write.
  - Raw tables aren't reachable.
  - Separately, the purge cron deletes old rows and keeps recent ones.
- `wrangler` is pinned to 4.158.0 with a committed lockfile.

### 3. Shared app data: `docs/data/restrooms.json` (nightly)
- 1,563 restrooms: 995 official (3 exact duplicate rows in the city table collapsed) plus 568 OpenStreetMap toilets from a committed snapshot.
- **Stable ids**: a hash of name and location, because the city table has no id and row numbers shift.
- Filter fields (accessible / changing table / gender-neutral) use **yes / limited / no / unknown**. Unknown is never treated as no.
- **Validation gate** before writing: row counts in range, at least 85% of official hours parsed, coordinates inside NYC, unique ids, well-formed masks. It raises instead of publishing.
- **Nightly GitHub Action** (`nightly-data.yml`): re-downloads the city table, rebuilds, and commits **only if the data changed**. It never touches the pre-registered analysis outputs. Pages republishes automatically. Verified with manual runs.

### 4. Display rules: `docs/assets/status.js` (5 Node tests, in CI)
- Open now uses New York time and season.
- Filters count hidden "unknown" places separately ("12 hidden because accessibility is unknown").
- Confirmations show **recency and counts** ("Confirmed open 12 days ago · 3 confirmations"), never a reliability percentage. The decay is an unvalidated heuristic.
- "Closed" appears only after 3 independent votes. Availability and cleanliness are separate votes (a test caught that "clean" was erasing "open"; fixed and tested).

### 5. App draft: `site_drafts/app/` (PWA, unpublished)
- Nearest restrooms open now (location or map tap), filter chips with hidden-unknown counts, an "include hours unknown" toggle, and a delivery-worker toggle that links to rights.
- Confirmation buttons appear only when an API is configured.
- Manifest, icon, and a **network-first** service worker (versioned cache, offline fallback only), so legal text and hours never go stale from the cache.
- Checked in a phone viewport against the local API: listing, filters, the confirmation round trip, and reload. A 5-minute cache made a new confirmation look missing after reload; the app now revalidates, and the server's cache is 1 minute.

## Bugs found and fixed this phase
1. **Live outage, about 20 minutes:** `.gitignore`'s `data/` also matched `docs/data/`, so the shared restroom file was never committed, and the live worker page fetched a missing file (404) after commit `270985e`. It passed locally because the file existed on disk. Fixed by scoping the ignore to `/data/` and committing the file; the live page was re-verified. **Lesson: check the live site after any push that adds new files.**
2. The nightly job's first run failed because the `app-data` command was never registered with the CLI (a silent edit miss). Fixed, with a test that every command has a parser entry.
3. The rule counted device tokens only. Network hashes were added (above).
4. Cleanliness votes erased availability votes. Fixed.

## What needs the owner (in order, each a separate decision)
1. **A Cloudflare account and `wrangler login`.** Free tier, done by the owner; credentials never pass through the project.
2. **Deploy the API.** Steps in `backend/README.md`: create D1, load schema and seed, set the `HMAC_KEY` and `TURNSTILE_SECRET` secrets, deploy.
3. **Publish the app page** (move `site_drafts/app` → `docs/app`).
4. **Turn community features on** by setting `apiBase` in `docs/config.js`. This means taking on dispute review as an ongoing job. Feedback from delivery workers first is recommended.
