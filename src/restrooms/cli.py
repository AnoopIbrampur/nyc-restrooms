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
    args = p.parse_args(argv)

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
