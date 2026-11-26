import re

import pytest

from restrooms.sources import SOURCES, Kind, by_key

FOUR_BY_FOUR = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")


def test_keys_unique():
    keys = [s.key for s in SOURCES]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("s", [s for s in SOURCES if s.kind is Kind.SOCRATA], ids=lambda s: s.key)
def test_socrata_ids_well_formed(s):
    assert FOUR_BY_FOUR.match(s.dataset_id)
    assert s.resource_url == f"https://{s.url}/resource/{s.dataset_id}.json"
    assert s.metadata_url.endswith(f"/api/views/{s.dataset_id}.json")


@pytest.mark.parametrize(
    "s", [s for s in SOURCES if s.kind is not Kind.SOCRATA], ids=lambda s: s.key
)
def test_non_socrata_have_full_urls(s):
    assert s.url.startswith("https://")
    assert not s.dataset_id
    with pytest.raises(ValueError):
        _ = s.metadata_url


def test_phases_in_range():
    assert all(1 <= s.phase <= 5 for s in SOURCES)


def test_by_key():
    assert by_key("nyc_restrooms").dataset_id == "i7jb-7jku"
    with pytest.raises(KeyError):
        by_key("nope")
