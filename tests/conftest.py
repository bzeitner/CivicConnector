import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    with (FIXTURES_DIR / name).open() as f:
        return json.load(f)


@pytest.fixture
def legistar_events():
    return load_fixture("legistar_events.json")


@pytest.fixture
def legistar_eventitems():
    return load_fixture("legistar_eventitems.json")


@pytest.fixture
def legistar_votes():
    return load_fixture("legistar_votes.json")


@pytest.fixture
def legistar_matter_histories():
    return load_fixture("legistar_matter_histories.json")


@pytest.fixture
def civicclerk_events():
    return load_fixture("civicclerk_events.json")
