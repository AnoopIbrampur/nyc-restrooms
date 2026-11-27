"""Aggregated reports file for the delivery-worker page (docs/worker/reports_public.json).

Restroom data for the page now comes from the shared, nightly-refreshed
docs/data/restrooms.json (restrooms.app_data). Until the API is deployed, the reports
file is the empty output of reports.public_summary().
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from restrooms.paths import PROCESSED, ROOT
from restrooms.reports import public_summary

OUT = ROOT / "docs" / "worker"


def export(today: date | None = None) -> dict:
    today = today or date.today()
    p = pd.read_parquet(PROCESSED / "places.parquet", columns=["place_id", "name", "lat", "lon"])
    summary = public_summary([], p, today)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reports_public.json").write_text(json.dumps(summary, indent=1))
    return {"places_listed": len(summary["places"])}
