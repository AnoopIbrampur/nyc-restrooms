import pytest
import requests
import responses

from restrooms.check import check_source
from restrooms.cli import main
from restrooms.sources import Kind, Source

SOC = Source("t_soc", Kind.SOCRATA, "Test", "data.example.gov", 1, "abcd-1234", ("a", "b"))
FILE = Source("t_file", Kind.FILE, "Test file", "https://files.example.com/x.pbf", 1)
API = Source(
    "t_api",
    Kind.API,
    "Test api",
    "https://api.example.com/r",
    1,
    expected_fields=("name", "latitude"),
    params={"lat": "1"},
)


def _meta(cols):
    return {"columns": [{"fieldName": c} for c in cols], "rowsUpdatedAt": 1764115200}


@responses.activate
def test_socrata_ok():
    responses.get(SOC.metadata_url, json=_meta(["a", "b", "c"]))
    responses.get(SOC.resource_url, json=[{"count": "42"}])
    r = check_source(SOC, requests.Session())
    assert r.ok and r.rows == 42 and r.updated == "2025-11-26" and r.missing == ()


@responses.activate
def test_socrata_missing_field_fails():
    responses.get(SOC.metadata_url, json=_meta(["a"]))
    responses.get(SOC.resource_url, json=[{"count": "42"}])
    r = check_source(SOC, requests.Session())
    assert not r.ok and r.missing == ("b",)


@responses.activate
def test_socrata_empty_fails():
    responses.get(SOC.metadata_url, json=_meta(["a", "b"]))
    responses.get(SOC.resource_url, json=[{"count": "0"}])
    assert not check_source(SOC, requests.Session()).ok


@responses.activate
def test_http_error_is_reported_not_raised():
    responses.get(SOC.metadata_url, status=404)
    r = check_source(SOC, requests.Session())
    assert not r.ok and "HTTPError" in r.error


@responses.activate
def test_file_head():
    responses.head(
        FILE.url,
        headers={"Content-Length": "2500000", "Last-Modified": "Wed, 26 Nov 2026 10:00:00 GMT"},
    )
    r = check_source(FILE, requests.Session())
    assert r.ok and r.size_mb == 2.5 and r.updated == "2026-11-26"


@responses.activate
def test_api_fields():
    responses.get(API.url, json=[{"name": "x", "latitude": 1.0}])
    assert check_source(API, requests.Session()).ok
    responses.replace(responses.GET, API.url, json=[{"name": "x"}])
    r = check_source(API, requests.Session())
    assert not r.ok and r.missing == ("latitude",)


@responses.activate
def test_api_empty_fails():
    responses.get(API.url, json=[])
    assert not check_source(API, requests.Session()).ok


def test_ingest_cli_passes_keys(monkeypatch):
    calls = []
    monkeypatch.setattr("restrooms.ingest.ingest", lambda keys, force=False: calls.append(keys))
    assert main(["ingest", "--only", "nyc_restrooms", "boroughs"]) == 0
    assert calls == [["nyc_restrooms", "boroughs"]]


@pytest.mark.live
def test_all_sources_live():
    assert main(["check-sources"]) == 0
