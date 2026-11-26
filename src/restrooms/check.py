"""Live checks that each registered source resolves and still has the fields we rely on."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from restrooms.sources import Kind, Source

UA = {"User-Agent": "nyc-restrooms-data-check/0.1"}
TIMEOUT = 120  # count(*) on large Socrata tables can be slow


@dataclass
class CheckResult:
    key: str
    ok: bool
    rows: int | None = None
    updated: str | None = None  # ISO date
    size_mb: float | None = None
    missing: tuple[str, ...] = ()
    error: str = ""


def _check_socrata(s: Source, session: requests.Session) -> CheckResult:
    meta = session.get(s.metadata_url, headers=UA, timeout=TIMEOUT)
    meta.raise_for_status()
    m = meta.json()
    columns = {c["fieldName"] for c in m.get("columns", [])}
    missing = tuple(f for f in s.expected_fields if f not in columns)
    ts = m.get("rowsUpdatedAt")
    updated = datetime.fromtimestamp(ts, UTC).date().isoformat() if ts else None
    cnt = session.get(s.resource_url, params={"$select": "count(*)"}, headers=UA, timeout=TIMEOUT)
    cnt.raise_for_status()
    row = cnt.json()[0]
    rows = int(next(iter(row.values())))
    return CheckResult(
        s.key, ok=not missing and rows > 0, rows=rows, updated=updated, missing=missing
    )


def _check_file(s: Source, session: requests.Session) -> CheckResult:
    r = session.head(s.url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    size = r.headers.get("Content-Length")
    lm = r.headers.get("Last-Modified")
    updated = None
    if lm:
        updated = datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z").date().isoformat()
    return CheckResult(
        s.key, ok=True, size_mb=round(int(size) / 1e6, 1) if size else None, updated=updated
    )


def _check_api(s: Source, session: requests.Session) -> CheckResult:
    r = session.get(s.url, params=s.params, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list) or not data:
        return CheckResult(s.key, ok=False, error="empty or non-list response")
    missing = tuple(f for f in s.expected_fields if f not in data[0])
    return CheckResult(s.key, ok=not missing, rows=len(data), missing=missing)


_CHECKERS = {Kind.SOCRATA: _check_socrata, Kind.FILE: _check_file, Kind.API: _check_api}


def make_session() -> requests.Session:
    """Session that retries throttling / transient server errors with backoff."""
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def check_source(s: Source, session: requests.Session | None = None) -> CheckResult:
    session = session or make_session()
    try:
        return _CHECKERS[s.kind](s, session)
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        return CheckResult(s.key, ok=False, error=f"{type(e).__name__}: {e}"[:200])
