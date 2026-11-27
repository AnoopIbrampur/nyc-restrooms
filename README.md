# nyc-restrooms

Where in New York City can you actually use a bathroom, right now?

**[Live map: walking time to the nearest open restroom, hour by hour](https://anoopibrampur.github.io/nyc-restrooms/)** · **[Delivery workers: your restroom rights](https://anoopibrampur.github.io/nyc-restrooms/worker/)**

Three parts (see [PLAN.md](PLAN.md)):

1. **Restroom deserts**: walking time to the nearest free, open restroom across NYC, by hour, weighted by foot traffic.
2. **Restroom-likelihood model**: for every place in the city, how likely you can use its restroom, and on what terms.
3. **Delivery-worker mode**: NYC app delivery workers' legal right to a restroom at pickup, the nearest public restrooms open now, and a rules-based way to report refusals.

Open data only (NYC Open Data, NY State Open Data, OpenStreetMap, Refuge Restrooms).

## Status
- **Phase 0**: repo + verified source registry (15 sources, all pass the live check).
- **Phase 1**: data layer done. 80,656 NYC places with per-source restroom evidence, parsed summer/winter hours, and delivery-worker coverage. Cross-source matching audited at 98% precision. See the [Phase 1 report](docs/phase1_report.md).
- **Phase 2**: restroom deserts (pre-registered). At 11 pm on a weekday, **85.3%** of subway entries are at a station with no free public restroom open (by its listed hours) within a 10-minute walk, vs **14.1%** at 9 am. If every public toilet with no listed hours were open all night, the 11 pm figure would be 19.2% (the pre-registered upper bound on access). An exploratory, post-hoc estimate that drops likely duplicates puts it near 56%. See the [findings](docs/phase2_findings.md), the [pre-registration](docs/phase2_prereg.md) and the [live interactive map](https://anoopibrampur.github.io/nyc-restrooms/).
- **Phase 3**: restroom-likelihood model. **Built, not yet tested.** Predictions are frozen for a pre-registered 200-place hand audit that hasn't been done, so the project ships the category baseline. See the [Phase 3 report](docs/phase3_interim.md).
- **Phase 4**: delivery-worker mode. Since Jan 26, 2026, NYC law (Admin Code §20-1527) lets app delivery workers use the restroom at *any* business where they pick up, with kitchen and safety exceptions. **[Live worker page](https://anoopibrampur.github.io/nyc-restrooms/worker/)**: rights, the official access card, public restrooms open now, and how reports will work. See the [Phase 4 report](docs/phase4_report.md) and [law notes](docs/phase4_law_notes.md).
- Next, **Phase 5**: app + reliability (reporting backend, confirmations).

## Quickstart
```bash
make setup          # uv sync
make test           # unit tests (no network)
make check-sources  # live check: every dataset resolves with the expected fields
uv run restrooms ingest   # download Phase 1 sources to data/raw (~520 MB)
uv run restrooms build    # data/processed/places.parquet + docs/phase1_build.json
uv run restrooms ridership && uv run restrooms walk-graph   # Phase 2 inputs
uv run restrooms deserts  # ~5 min: walk times + docs/phase2_results.json
uv run restrooms condition && uv run restrooms export-map
uv run restrooms likelihood   # Phase 3 model + baseline -> data/processed/restroom_likelihood.parquet
uv run restrooms audit-score  # once, after the audit sheet is filled
uv run restrooms worker-export  # Phase 4 data for docs/worker/
```

Sources live in [`src/restrooms/sources.py`](src/restrooms/sources.py). A dataset goes in only after `check-sources` confirms it resolves. A weekly GitHub Action re-checks them.
