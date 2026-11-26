"""Filesystem layout. `data/` is gitignored; `docs/` holds committed reports/manifests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
DOCS = ROOT / "docs"
MANIFEST = DOCS / "data_manifest.json"


def ensure_dirs() -> None:
    for p in (RAW, PROCESSED, DOCS):
        p.mkdir(parents=True, exist_ok=True)
