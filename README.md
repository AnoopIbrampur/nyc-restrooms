# nyc-restrooms

Where in New York City can you actually use a bathroom, right now?

Three parts (see [PLAN.md](PLAN.md)):

1. **Restroom deserts**: walking time to the nearest free, open restroom across NYC, by hour, weighted by foot traffic.
2. **Restroom-likelihood model**: for every place in the city, how likely you can use its restroom, and on what terms.
3. **Delivery-worker mode**: food pickup spots where app delivery workers are likely entitled to a bathroom under NYC law, plus their rights.

Open data only (NYC Open Data, NY State Open Data, OpenStreetMap, Refuge Restrooms).

## Status
- **Phase 0**: repo + verified source registry (15 sources, all pass the live check).
- **Phase 1**: data layer done. 80,656 NYC places with per-source restroom evidence, parsed summer/winter hours, and delivery-worker coverage. Cross-source matching audited at 98% precision. See the [Phase 1 report](docs/phase1_report.md).
- Next, **Phase 2**: restroom deserts.

## Quickstart
```bash
make setup          # uv sync
make test           # unit tests (no network)
make check-sources  # live check: every dataset resolves with the expected fields
uv run restrooms ingest   # download Phase 1 sources to data/raw (~520 MB)
uv run restrooms build    # data/processed/places.parquet + docs/phase1_build.json
```

Sources live in [`src/restrooms/sources.py`](src/restrooms/sources.py). A dataset goes in only after `check-sources` confirms it resolves. A weekly GitHub Action re-checks them.
