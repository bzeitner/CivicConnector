"""Phase 3: CivicClerk connector tests (Lacey pilot).

Parsing/mapping logic is exercised offline against pinned fixtures
(captured live 2026-08-16 against laceywa.api.civicclerk.com), matching the
Legistar connector's pattern (Phase 2). `CivicClerkConnector` itself is
exercised with a fake fetch_json/fetch_text serving those same fixtures.

Phase 3 exit-criteria finding, verified live (documented in this idea's
research entry, not part of this automated suite):

- `GetMeetingFileStream(fileId=..., plainText=true)` returns HTTP 200 plain
  text for a real Lacey agenda PDF (event 1390, fileId 4059) — verified
  end-to-end.
- `Meetings/GetMeetingItemMinutesVotes(id=...)` returns HTTP 200 but an
  empty `value: []` for every one of 7 distinct Lacey meetings tried (both
  event ids and agendaIds). No GET-accessible way to enumerate the
  item-level ids the function's `id` parameter most likely expects was
  found (`Meetings(id)` 404s, `Sections` is POST-only/405 on GET).
  **Finding: NO** — vote data is not confirmed populated/reachable for
  Lacey via this API surface. This connector never returns Vote records
  and get_items() returns [] rather than guessing.
"""

from datetime import datetime

from civicconnector.connectors.civicclerk import (
    CivicClerkConnector,
    coverage_table,
    parse_body,
    parse_documents,
    parse_event,
)
from civicconnector.models import Body, Document, Meeting


def test_parse_body(civicclerk_categories):
    category = civicclerk_categories["value"][0]
    body = parse_body(category, jurisdiction_id="laceywa-civicclerk")
    assert isinstance(body, Body)
    assert body.native_id == str(category["id"])
    assert body.name == category["categoryDesc"]


def test_parse_event(civicclerk_events_council):
    event = civicclerk_events_council["value"][0]
    meeting = parse_event(event)
    assert isinstance(meeting, Meeting)
    assert meeting.native_id == str(event["id"])
    assert meeting.body_id == str(event["categoryId"])
    assert isinstance(meeting.starts_at, datetime)


def test_parse_event_picks_up_agenda_and_minutes_urls(civicclerk_events_council):
    # Find an event whose fixture publishedFiles include both an Agenda and
    # a Minutes entry (research entry #80/#205: coverage is inconsistent
    # across events, so the parser must handle both present and absent).
    event = next(
        e
        for e in civicclerk_events_council["value"]
        if any(f["type"] == "Minutes" for f in e["publishedFiles"])
    )
    meeting = parse_event(event)
    assert meeting.agenda_url is not None
    assert meeting.minutes_url is not None


def test_parse_documents_only_includes_present_files(civicclerk_events_council):
    event = civicclerk_events_council["value"][0]
    docs = parse_documents(event, meeting_native_id=str(event["id"]))
    assert docs
    assert all(isinstance(d, Document) for d in docs)
    assert {d.kind for d in docs} <= {"agenda", "agenda_packet", "minutes", "notice"}


def test_coverage_table_reports_zero_votes_per_documented_finding(civicclerk_events_council):
    table = coverage_table(civicclerk_events_council["value"])
    assert table
    for row in table:
        # Phase 3 finding: GetMeetingItemMinutesVotes was not confirmed
        # populated/reachable for any Lacey meeting tried, so this
        # connector never claims vote coverage.
        assert row["items_with_votes"] == 0


class _FakeCivicClerkApi:
    """Serves pinned fixtures keyed by path, standing in for a live
    laceywa.api.civicclerk.com response."""

    def __init__(self, categories, events):
        self._categories = categories["value"]
        self._events = events["value"]

    def fetch_json(self, url, params):
        skip = params.get("$skip", 0)
        top = params["$top"]
        if url.endswith("/EventCategories"):
            page = self._categories
        elif url.endswith("/Events"):
            page = self._events
        else:
            raise AssertionError(f"unexpected URL in fake API: {url}")
        return {"value": page[skip : skip + top]}

    def fetch_text(self, url):
        return "fake plain text agenda content"


def test_civicclerk_connector_end_to_end_against_fixtures(
    civicclerk_categories, civicclerk_events_council
):
    api = _FakeCivicClerkApi(civicclerk_categories, civicclerk_events_council)
    connector = CivicClerkConnector(
        tenant="laceywa", fetch_json=api.fetch_json, fetch_text=api.fetch_text
    )

    bodies = connector.list_bodies()
    assert bodies and all(isinstance(b, Body) for b in bodies)

    meetings = connector.list_meetings()
    assert meetings and all(isinstance(m, Meeting) for m in meetings)

    target = meetings[0]

    # get_items is documented as unsupported for this tenant (Phase 3
    # finding) — it must return [] rather than guess.
    assert connector.get_items(target) == []

    docs = connector.get_documents(target)
    assert all(isinstance(d, Document) for d in docs)

    text = connector.get_document_text(file_id="4059")
    assert text == "fake plain text agenda content"


def test_paginate_stops_when_page_shorter_than_top(civicclerk_categories):
    calls = []

    def fetch(url, params):
        calls.append(dict(params))
        page = civicclerk_categories["value"]
        return {"value": page if params["$skip"] == 0 else []}

    connector = CivicClerkConnector(tenant="laceywa", fetch_json=fetch)
    bodies = connector.list_bodies()
    assert len(bodies) == len(civicclerk_categories["value"])
    assert len(calls) == 1, "should not request a second page once a short page is returned"
