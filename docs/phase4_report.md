# Phase 4 report: delivery-worker mode

**Status (2026-11-27):** built, checked, and **published** with the project owner's approval at https://anoopibrampur.github.io/nyc-restrooms/worker/ (source: `docs/worker/`).

## The biggest finding: the right is per pickup, not per place
The plan (written 2026-11-26 from DCWP summaries) assumed the restroom right came only through restaurants' contracts with delivery apps (Local Law 117 of 2021), so the map would label restaurants "likely covered". **Reading the enacted texts changed that.** Local Law 123 of 2025 added **Admin Code §20-1527 (in effect Jan 26, 2026)**: *any* food service establishment *or other business* must give a contracted delivery worker access to a restroom on the premises when the worker picks up goods there. That includes a staff restroom if there's no customer one, except where reaching it means walking through a kitchen, food-prep, storage or dishwashing area, or creates an obvious health or safety risk. Full notes: [`phase4_law_notes.md`](phase4_law_notes.md).

Consequences for the design:
- **No place is labeled "must let you in" or "violating".** The page states the rule and its exceptions. The real uncertainty is the exceptions (kitchen layout), which no dataset shows.
- Phase 1's `likely_covered_pickup` column was renamed `dohmh_food_service`, because it says nothing about legal coverage. The plan, the Phase 1 report and the README were corrected.
- Phase 3's restroom probabilities **aren't used here**. Their "none" class includes staff-only restrooms, and under this law a staff restroom counts.

## What the worker page does (`docs/worker/index.html`)
1. **Your right, in short**: four plain-language bullets, the official DCWP bathroom access card (linked, not rehosted), file-a-complaint and call-311 buttons.
2. **Public restrooms open now**: the Phase 2 primary set (1,011 restrooms with listed hours). Open/closed comes from NYC time and season (Apr–Oct summer hours, conservative reading A). "Use my location" (stays on the phone) or tap the map; the five nearest show with straight-line distance, a walking estimate (×1.25 detour, 1.25 m/s, as in Phase 2) and OSM walking directions. Checked: on a Thursday evening in November, 96 were open.
3. **What the law says**: the statute quote, exceptions, remedies ($200 per refusal to the worker; $500 / $750 / $1,000 civil penalties), the 2021 contract rule, and litigation status.
4. **Reports from workers**: shows only already-aggregated JSON (empty for now). The report button is **disabled** until a server exists (Phase 5).
5. **Languages**: DCWP's official notice of rights in all 12 languages it publishes (including Spanish, French and Bengali), all 12 links taken from DCWP's English page. No legal text was translated by this project.
6. Footer: last-checked date, not legal advice, links to the law notes and code.

Checked in a 375×812 phone viewport: no console errors, no horizontal scroll, NYC-time hour correct, nearest-restroom list correct.

## Report publishing rule (`src/restrooms/reports.py`, 10 tests)
Raw reports never reach the page. Only `public_summary()` output does.
- Outcomes: let in / refused / told it's through the kitchen (a legal exception, never counted as a refusal) / no restroom. No free text, no identity, no location beyond the place.
- One vote per device per place (latest within 180 days).
- A business is listed only with **at least 3 distinct devices reporting refusal**, refusals **at least half** of its devices, and **no open dispute**. Disputed listings are withheld pending review.
- Area rollups (H3 res-7) need at least 10 votes from at least 5 devices and publish only a refused share.
- Public wording: "workers reported being refused here", never "violates the law".

## Not done / next
- **Reporting backend** (Phase 5): storage, device tokens, rate limiting and a dispute process. Until then the button stays disabled.
- **Interface translations**: the page is in English, with official translated notices linked. Translating the interface needs a native-speaker review; legal text stays DCWP's.
- **Outreach**: feedback from a delivery-worker group (for example, Los Deliveristas Unidos) before any public launch is recommended. Not contacted; that's the project owner's call.
- **Food carts and trucks** aren't in the restroom data. The legal right still applies to any pickup.
