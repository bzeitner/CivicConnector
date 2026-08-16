"""Phase 2: Legistar connector tests.

Parsing/mapping logic is exercised offline against the pinned fixtures in
tests/fixtures/ (captured live in research entries #80/#202), so the suite
stays fast and doesn't depend on network access. `LegistarConnector` itself
is exercised with a fake `fetch_json` that serves those same fixtures,
proving the four-method interface end-to-end without a live call.

A one-time live run (documented in this idea's research entry, not part of
this automated suite) confirmed `get_items` against Olympia events
7259/7258/7257/7256/7255 reproduces research entry #80's measured coverage
table exactly (items: 4/18/15/13/12; items_with_action: 1/7/5/0/0;
roll_call_flagged: 1/2/1/1/1), meeting Phase 2's exit criteria.
"""

from datetime import datetime

import pytest

from civicconnector.connectors.legistar import (
    LegistarConnector,
    coverage_table,
    parse_body,
    parse_documents,
    parse_event,
    parse_event_item,
)
from civicconnector.models import ActionSource, AgendaItem, Body, Document, Meeting


def test_parse_body(legistar_bodies):
    body = parse_body(legistar_bodies[0], jurisdiction_id="olympia-legistar")
    assert isinstance(body, Body)
    assert body.native_id == str(legistar_bodies[0]["BodyId"])
    assert body.name == legistar_bodies[0]["BodyName"]


def test_parse_event(legistar_events):
    meeting = parse_event(legistar_events[0])
    assert isinstance(meeting, Meeting)
    assert meeting.native_id == str(legistar_events[0]["EventId"])
    assert meeting.body_id == str(legistar_events[0]["EventBodyId"])
    assert isinstance(meeting.starts_at, datetime)


def test_parse_event_item_sets_action_source_from_presence_of_action_name(legistar_eventitems):
    with_action = [i for i in legistar_eventitems if i.get("EventItemActionName")]
    without_action = [i for i in legistar_eventitems if not i.get("EventItemActionName")]
    assert with_action and without_action, "fixture should contain both cases"

    parsed_with = parse_event_item(with_action[0], meeting_native_id="x")
    assert parsed_with.action_source is ActionSource.API
    assert parsed_with.confidence == 1.0

    parsed_without = parse_event_item(without_action[0], meeting_native_id="x")
    assert parsed_without.action_source is ActionSource.NONE
    assert parsed_without.confidence == 0.0

    # This connector is API-only (Phase 2); it never claims minutes-PDF
    # provenance, since that requires the PDF-parsing work in a later phase.
    assert all(
        parse_event_item(i, meeting_native_id="x").action_source is not ActionSource.MINUTES_PDF
        for i in legistar_eventitems
    )


def test_parse_documents_only_includes_present_urls():
    meeting = Meeting(body_id="1", native_id="1", starts_at=datetime.now(), agenda_url="http://a")
    docs = parse_documents(meeting)
    assert len(docs) == 1
    assert docs[0].kind == "agenda"

    meeting_none = Meeting(body_id="1", native_id="1", starts_at=datetime.now())
    assert parse_documents(meeting_none) == []


def test_coverage_table_matches_research_entry_80_shape(legistar_eventitems):
    items = [parse_event_item(i, meeting_native_id="7259") for i in legistar_eventitems]
    table = coverage_table({"7259": items})
    assert table == [
        {
            "event_id": "7259",
            "items": len(items),
            "items_with_action": sum(1 for i in items if i.action_source is ActionSource.API),
            "roll_call_flagged": sum(1 for i in items if i.roll_call),
        }
    ]


class _FakeLegistarApi:
    """Serves the pinned fixtures keyed by path, standing in for a live
    webapi.legistar.com response so LegistarConnector can be exercised
    end-to-end without network access."""

    def __init__(self, bodies, events, eventitems):
        self._bodies = bodies
        self._events = events
        self._eventitems = eventitems

    def fetch_json(self, url, params):
        skip = params.get("$skip", 0)
        if url.endswith("/bodies"):
            page = self._bodies
        elif url.endswith("/events"):
            page = self._events
        elif "/eventitems" in url:
            page = self._eventitems
        else:
            raise AssertionError(f"unexpected URL in fake API: {url}")
        return page[skip : skip + params["$top"]]


def test_legistar_connector_end_to_end_against_fixtures(
    legistar_bodies, legistar_events, legistar_eventitems
):
    api = _FakeLegistarApi(legistar_bodies, legistar_events, legistar_eventitems)
    connector = LegistarConnector(client="olympia", fetch_json=api.fetch_json)

    bodies = connector.list_bodies()
    assert bodies and all(isinstance(b, Body) for b in bodies)

    meetings = connector.list_meetings()
    assert meetings and all(isinstance(m, Meeting) for m in meetings)

    # legistar_events.json and legistar_eventitems.json were captured from
    # different sample events (per test_connector_interface.py), so target
    # the eventitems fixture's own event id directly.
    target = Meeting(
        body_id="unknown",
        native_id=str(legistar_eventitems[0]["EventItemEventId"]),
        starts_at=meetings[0].starts_at,
        agenda_url=meetings[0].agenda_url,
    )
    items = connector.get_items(target)
    assert items and all(isinstance(i, AgendaItem) for i in items)

    docs = connector.get_documents(target)
    assert all(isinstance(d, Document) for d in docs)


def test_paginate_stops_when_page_shorter_than_top(legistar_bodies):
    calls = []

    def fetch(url, params):
        calls.append(dict(params))
        return legistar_bodies if params["$skip"] == 0 else []

    connector = LegistarConnector(client="olympia", fetch_json=fetch)
    bodies = connector.list_bodies()
    assert len(bodies) == len(legistar_bodies)
    assert len(calls) == 1, "should not request a second page once a short page is returned"
