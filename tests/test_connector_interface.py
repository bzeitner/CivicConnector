from datetime import datetime
from typing import List, Optional

import pytest

from civicconnector.connectors import Connector
from civicconnector.models import AgendaItem, Body, Document, Meeting


def test_connector_is_abstract():
    with pytest.raises(TypeError):
        Connector()  # missing implementations


class _FixtureConnector(Connector):
    """Minimal in-memory connector used to prove the four-method contract,
    backed by the pinned Legistar fixtures rather than a live call."""

    def __init__(self, events, eventitems):
        self._events = events
        self._eventitems = eventitems

    def list_bodies(self) -> List[Body]:
        seen = {}
        for e in self._events:
            seen[e["EventBodyId"]] = Body(
                jurisdiction_id="olympia-wa",
                native_id=str(e["EventBodyId"]),
                name=e["EventBodyName"],
            )
        return list(seen.values())

    def list_meetings(self, since: Optional[datetime] = None) -> List[Meeting]:
        return [
            Meeting(
                body_id=str(e["EventBodyId"]),
                native_id=str(e["EventId"]),
                starts_at=datetime.fromisoformat(e["EventDate"]),
                status=e["EventAgendaStatusName"],
                agenda_url=e["EventAgendaFile"],
            )
            for e in self._events
        ]

    def get_items(self, meeting: Meeting) -> List[AgendaItem]:
        return [
            AgendaItem(meeting_id=meeting.native_id, native_id=str(i["EventItemId"]))
            for i in self._eventitems
            if str(i["EventItemEventId"]) == meeting.native_id
        ]

    def get_documents(self, meeting: Meeting) -> List[Document]:
        if not meeting.agenda_url:
            return []
        return [Document(meeting_id=meeting.native_id, kind="agenda", url=meeting.agenda_url)]


def test_fixture_connector_satisfies_interface(legistar_events, legistar_eventitems):
    connector = _FixtureConnector(legistar_events, legistar_eventitems)
    bodies = connector.list_bodies()
    assert bodies and all(isinstance(b, Body) for b in bodies)

    meetings = connector.list_meetings()
    assert meetings and all(isinstance(m, Meeting) for m in meetings)

    # legistar_events.json and legistar_eventitems.json were captured from
    # different sample events, so build the target meeting directly from the
    # eventitems fixture rather than assuming it's present in list_meetings().
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
