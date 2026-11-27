"""Command line entry point: `restrooms check-sources` / `restrooms ingest --dry-run`."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

from restrooms.check import CheckResult, check_source
from restrooms.sources import SOURCES, Source


def _fmt(s: Source, r: CheckResult) -> str:
    status = "OK  " if r.ok else "FAIL"
    detail = []
    if r.rows is not None:
        detail.append(f"rows={r.rows:,}")
    if r.size_mb is not None:
        detail.append(f"size={r.size_mb}MB")
    if r.updated:
        detail.append(f"updated={r.updated}")
    if r.missing:
        detail.append(f"missing={','.join(r.missing)}")
    if r.error:
        detail.append(r.error)
    return f"{status} P{s.phase} {s.key:28s} {' '.join(detail)}"


def run_checks(phase: int | None = None) -> int:
    sources = [s for s in SOURCES if phase is None or s.phase <= phase]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(check_source, sources))
    for s, r in zip(sources, results, strict=True):
        print(_fmt(s, r))
    failed = [r.key for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} sources OK")
    return 1 if failed else 0


def _ridership() -> None:
    from restrooms.ridership import ingest_ridership

    ingest_ridership()


def _walk_graph() -> None:
    import json

    from restrooms.paths import DOCS, PROCESSED, RAW
    from restrooms.walk import build_graph, network_checks

    g, stats = build_graph(RAW / "new-york-latest.osm.pbf")
    g.save(PROCESSED / "walk_graph.npz")
    stats["checks"] = network_checks(g)
    stats["checks"]["note_over_3"] = (
        "inspected 2026-11-26: water crossings with no walkable bridge "
        "(Throgs Neck/Whitestone, East River at Astoria)"
    )
    (DOCS / "phase2_walk_graph.json").write_text(json.dumps(stats, indent=2) + "\n")
    print(stats)


def _deserts() -> None:
    from restrooms.deserts import run

    run()


def _condition() -> None:
    import json

    import pandas as pd

    from restrooms.condition import condition_overlay
    from restrooms.paths import DOCS, PROCESSED

    df, stats = condition_overlay(pd.read_parquet(PROCESSED / "places.parquet"))
    df.to_csv(DOCS / "phase2_park_condition.csv", index=False)
    (DOCS / "phase2_condition.json").write_text(json.dumps(stats, indent=2, default=str) + "\n")
    print(stats)


def _export_map() -> None:
    from restrooms.export_map import export

    export()


def _likelihood() -> None:
    from restrooms.likelihood import run

    run()


def _audit_score() -> None:
    import json

    from restrooms.audit import universe
    from restrooms.audit_score import score

    counts = universe()["group"].value_counts().to_dict()
    print(json.dumps(score(counts), indent=2))


def _worker_export() -> None:
    from restrooms.worker_export import export

    export()


PHASE2 = {
    "ridership": _ridership,
    "walk-graph": _walk_graph,
    "deserts": _deserts,
    "condition": _condition,
    "export-map": _export_map,
    "likelihood": _likelihood,
    "audit-score": _audit_score,
    "worker-export": _worker_export,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="restrooms")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-sources", help="verify every registered source is live")
    c.add_argument("--phase", type=int, help="only sources needed up to this phase")
    i = sub.add_parser("ingest", help="download sources (Phase 1)")
    i.add_argument("--dry-run", action="store_true", help="check sources, download nothing")
    i.add_argument("--only", nargs="+", help="source keys to ingest (default: all Phase 1)")
    i.add_argument("--force", action="store_true", help="re-download files even if fresh")
    sub.add_parser("build", help="build processed tables from data/raw (Phase 1)")
    sub.add_parser("ridership", help="download subway entries by hour of week (Phase 2)")
    sub.add_parser("walk-graph", help="build the pedestrian network (Phase 2)")
    sub.add_parser("deserts", help="walk times + headline metrics (Phase 2, ~5 min)")
    sub.add_parser("condition", help="Parks restroom condition overlay (Phase 2)")
    sub.add_parser("export-map", help="write docs/map/data.json (Phase 2)")
    sub.add_parser(
        "likelihood", help="train restroom model + baseline, predict all places (Phase 3)"
    )
    sub.add_parser("audit-score", help="score the filled audit sheet, once (Phase 3)")
    sub.add_parser(
        "worker-export", help="data for the delivery-worker page in docs/worker (Phase 4)"
    )
    args = p.parse_args(argv)

    if args.cmd in PHASE2:
        PHASE2[args.cmd]()
        return 0

    if args.cmd == "check-sources":
        return run_checks(args.phase)
    if args.cmd == "ingest":
        if args.dry_run:
            return run_checks()
        from restrooms.ingest import PHASE1, ingest

        ingest(args.only or PHASE1, force=args.force)
        return 0
    if args.cmd == "build":
        from restrooms.build import build

        build()
        return 0
    print(f"unknown command {args.cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
