# Phase 3 interim: model trained, predictions frozen, waiting on the audit

**Status (2026-11-27):** everything up to scoring is done and pushed. Phase 3 can't finish until the 200-place audit comes back. The result (beats baseline / loses / not supported) is decided by the pre-registered rule in [`phase3_prereg.md`](phase3_prereg.md).

## Timeline (all on GitHub, in order)
1. `782a778`: pre-registration, audit protocol, category mapping (00:52 UTC)
2. `a25d71e`: seeded audit sample, blank sheet
3. `58dcfc1`: model, baseline, and **frozen predictions for all 320 audit rows**, plus the scoring code
4. *(pending)* filled sheet → `restrooms audit-score` → results

## Universe and labels
- **70,184 places** in 8 groups. 8,766 excluded (parks, playgrounds, places of worship, Refuge-only, untyped).
- **Training labels (OSM):** 1,124 for stage 1 ("has a usable restroom", 83% yes) and 226 for stage 2 ("free vs customers-only", 32% free). All 320 audit rows are held out of training, including 7 that had OSM labels.
- **Category mapping check:** cuisine-derived groups agree with OSM groups 60.5% of the time on 13,432 matched restaurants.

## Model selection (grouped CV on OSM labels: internal and biased, not the test)
Folds are grouped by chain name and by H3 resolution-7 cell.

| Stage | Baseline | Logistic | Gradient boosting |
|---|---|---|---|
| 1: has restroom (n = 1,124) | 0.3314 | **0.3209** | 0.3412 |
| 2: free if has restroom (n = 226) | **0.5509** | 0.5565 | 0.7422 |

Logistic regression was chosen for both stages (the pre-registration allows only model candidates, not the baseline). Regularization per stage came from a grouped-CV grid (stage 1 C = 1.0, stage 2 C = 0.2). **In stage 2, even the best model is slightly worse than the baseline.** The few access labels don't support more than category rates, so any gain on the audit would have to come from stage 1.

## What the model predicts (mean over each group)
| Group | Free | Customers | None |
|---|---|---|---|
| restaurant | 0.10 | 0.82 | 0.08 |
| bar | 0.45 | 0.54 | 0.02 |
| cafe / bakery | 0.20 | 0.44 | 0.36 |
| quick service | 0.07 | 0.37 | 0.56 |
| grocery | 0.38 | 0.19 | 0.44 |
| retail | 0.24 | 0.24 | 0.53 |
| services / health | 0.21 | 0.60 | 0.19 |
| lodging / culture / civic | 0.35 | 0.52 | 0.13 |

Some of these look suspicious and are exactly what the audit tests. A 45% "free" rate for bars and 38% for groceries come from a handful of OSM `permissive` tags. In practice, NYC bars and groceries rarely let non-customers use the restroom.

## Smoke test of the scoring code
Run on a synthetic, randomly filled copy of the sheet (not committed): 200 rows scored, reserves applied in order, and a 95% CI on the log-loss difference about ±0.1 wide. **Only a clear difference will register as "beats baseline" or "loses".**

## The audit
- Sheet: [`phase3_audit_sheet.csv`](phase3_audit_sheet.csv). Rules: [`phase3_audit_protocol.md`](phase3_audit_protocol.md).
- 200 places (25 per group) plus 15 ordered reserves per group. 62% have a listed phone number (92–96% of restaurants, about 40% of shops and services). The rest need a lookup by name and address, or a visit.
- **Rough effort:** about 3 minutes per answered call, plus retries and lookups, so roughly **8–12 hours spread over several days**. Calls work best mid-afternoon, outside meal rushes.
