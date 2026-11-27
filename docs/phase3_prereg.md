# Phase 3 pre-registration: restroom-likelihood model

Written 2026-11-27, **before any model was trained, before the audit sample was drawn, and before any audit outcome exists.** Pushed to GitHub as its own commit.

## Question
For an NYC place (café, shop, hotel, clinic, …) with no restroom information, can a model trained on OpenStreetMap tags predict whether a member of the public can use a restroom there, and on what terms, **better than per-category rates**?

## Target (three classes)
- **free walk-in**: anyone can use it without buying anything
- **customers only**: available to customers, patrons or patients (including "only if you buy something", or a posted "customers only" sign)
- **none**: no restroom, or staff only

The model outputs P(free), P(customers), P(none) for every place in the universe.

## Universe
70,184 places in eight groups (`src/restrooms/categories.py`): restaurant, quick_service, cafe_bakery, bar, grocery, retail, services_health, lodging_culture_civic. Restaurants found only in DOHMH get a group from their cuisine (mapping committed in the same file). **Excluded**: official restrooms, OSM public toilets (Phase 2 covers them), parks, playgrounds, gardens, places of worship, Refuge-only records, and untyped features (8,766 places).

*Known weakness, measured before modeling:* on 13,432 DOHMH↔OSM matched restaurants, the cuisine-derived group agrees with the OSM group 60.5% of the time. Most disagreements are restaurant vs bar and restaurant vs quick service.

## Training labels (OSM only)
- **Stage 1, has a usable restroom**: `toilets=yes` or `toilets=customers` → yes. `toilets=no`, or `toilets:access=private`/`no` → no.
- **Stage 2, free vs customers** (only where stage 1 is yes): `toilets:access` = yes, public or permissive → free. `toilets:access=customers` or `toilets=customers` → customers. `toilets=yes` with no access tag is used in stage 1 only.
- Three-class output: P(free) = P(yes)·P(free | yes), P(customers) = P(yes)·(1 − P(free | yes)), P(none) = 1 − P(yes).
- **Refuge presence is a feature, not a label.**
- **Every audited place (sample and reserves) is dropped from training before fitting.**

## Baseline
The same two-stage product, with each stage's probability a hierarchically smoothed rate: fine class → group → global. Each level shrinks toward its parent with **10 pseudo-counts**. It's fit on the same training labels.

## Model
Chosen *only* by grouped cross-validation on the OSM labels (folds grouped by chain/brand name and by H3 resolution-7 cell, so chains and blocks can't leak across folds). Candidates: L2 logistic regression and gradient-boosted trees for each stage. Features may include fine class, group, chain or brand, borough, listed weekly open hours, DOHMH presence, Refuge presence, building footprint area where a building ID links, and nearby place density. That cross-validation is internal, biased by OSM's labeling, and never used for the pass rule.

**Freeze:** before the audit is handed over, model and baseline probabilities for every audit row (sample and reserves) are written to `docs/phase3_frozen_predictions.csv`, committed and pushed. Scoring uses that file only.

## Audit (the test set)
- **Sample**: stratified simple random sample from the universe, **25 places per group × 8 groups = 200**, seeded (`20261127`). Each group also gets a **reserve list of 15**, in fixed random order.
- **Who and how**: the project owner phones the place (number given when known, otherwise looked up by name and address) or visits. The model author never contacts businesses.
- **Coding rules**: see `docs/phase3_audit_protocol.md`, written before the sample is drawn.
- **Unreachable** (no answer after 2 tries, permanently closed, not found): recorded with that outcome, excluded from scoring, and replaced by the **next reserve in order** for that group. The auditor never chooses a substitute. The closed or not-found rate is reported separately.

## Metrics and pass rule
- **Probability floor**: every class probability is floored at 0.005, then renormalized, for both model and baseline.
- **Primary metric**: post-stratified (group population share) three-class log-loss. **Δ = baseline log-loss − model log-loss.** 95% CI from 10,000 bootstrap resamples within strata.
- **Outcomes, fixed in advance:**
  - **Beats baseline**: CI of Δ entirely above 0
  - **Loses**: CI of Δ entirely below 0
  - **Not supported**: CI includes 0
- **Secondary**: post-stratified three-class Brier score (same Δ and CI); unweighted log-loss and Brier; per-group log-loss; binary stage-1 log-loss (restroom vs none); the closed or not-found rate.
- Whatever the outcome, it's published. If the model doesn't beat the baseline, the map uses the baseline.

## Stated expectation (reported either way)
"Not supported" is the most likely outcome: training labels are thin outside food and drink, and 200 rows give a wide interval. A "beats baseline" result would most likely come from chains and from groups with few labels, where the baseline falls back to the global rate.
