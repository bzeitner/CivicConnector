"""Legistar connector (Phase 2, Olympia pilot).

Talks to the unauthenticated, undocumented-but-real Legistar Web API
(``webapi.legistar.com/v1/{client}``), verified live against the ``olympia``
client in IdeaFlow idea #32 research entries #80 and #202.

HTTP fetching is injected via ``fetch_json`` so the parsing/mapping logic
(the part worth unit-testing) can be exercised offline against the pinned
fixtures in ``tests/fixtures/`` without a live network call, matching the
Phase 1 contract-test pattern. The default ``fetch_json`` uses ``requests``
against the real API.

Coverage caveat (research entry #80, reconfirmed live in #202): structured
``EventItemActionName`` data lands on roughly 0-40% of items and is absent
until minutes are processed; named vote rosters are frequently empty even on
items with a recorded action. This connector never infers an action or vote
that the API did not return — it records ``ActionSource.NONE`` and lets the
coverage table make the gap visible, per the plan's extraction rule.

``ActionSource.MINUTES_PDF`` is reserved for a future phase that parses
minutes PDFs; this connector (API-only) never sets it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from civicconnector.connectors.base import Connector
from civicconnector.models import ActionSource, AgendaItem, Body, Document, Meeting

DEFAULT_BASE_URL = "https://webapi.legistar.com/v1"
PAGE_SIZE = 1000  # documented Legistar reply cap


def _requests_fetch_json(url: str, params: Dict[str, Any]) -> Any:
    import requests

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_body(raw: Dict[str, Any], jurisdiction_id: str) -> Body:
    return Body(
        jurisdiction_id=jurisdiction_id,
        native_id=str(raw["BodyId"]),
        name=raw["BodyName"],
        type=raw.get("BodyTypeName"),
    )


def parse_event(raw: Dict[str, Any]) -> Meeting:
    return Meeting(
        body_id=str(raw["EventBodyId"]),
        native_id=str(raw["EventId"]),
        starts_at=datetime.fromisoformat(raw["EventDate"]),
        status=raw.get("EventAgendaStatusName"),
        agenda_url=raw.get("EventAgendaFile") or None,
        minutes_url=raw.get("EventMinutesFile") or None,
        video_url=raw.get("EventInSiteURL") or None,
    )


def parse_event_item(raw: Dict[str, Any], meeting_native_id: str) -> AgendaItem:
    action_name = raw.get("EventItemActionName")
    action_source = ActionSource.API if action_name else ActionSource.NONE
    return AgendaItem(
        meeting_id=meeting_native_id,
        native_id=str(raw["EventItemId"]),
        seq=raw.get("EventItemAgendaSequence"),
        number=raw.get("EventItemAgendaNumber"),
        title=raw.get("EventItemTitle"),
        matter_id=str(raw["EventItemMatterId"]) if raw.get("EventItemMatterId") else None,
        action_name=action_name,
        passed=raw.get("EventItemPassedFlag"),
        roll_call=bool(raw.get("EventItemRollCallFlag")),
        action_source=action_source,
        # Confidence mirrors action_source until Phase 3+ calibrates this
        # against measured lag/coverage data across more events.
        confidence=1.0 if action_source is ActionSource.API else 0.0,
    )


def parse_documents(meeting: Meeting) -> List[Document]:
    docs = []
    if meeting.agenda_url:
        docs.append(Document(meeting_id=meeting.native_id, kind="agenda", url=meeting.agenda_url))
    if meeting.minutes_url:
        docs.append(Document(meeting_id=meeting.native_id, kind="minutes", url=meeting.minutes_url))
    return docs


def coverage_table(items_by_event: Dict[str, List[AgendaItem]]) -> List[Dict[str, Any]]:
    """Per-event coverage row, matching the table format in research entry #80:
    items, items with a structured action, and roll-call-flagged items."""
    rows = []
    for event_id, items in items_by_event.items():
        rows.append(
            {
                "event_id": event_id,
                "items": len(items),
                "items_with_action": sum(1 for i in items if i.action_source is ActionSource.API),
                "roll_call_flagged": sum(1 for i in items if i.roll_call),
            }
        )
    return rows


class LegistarConnector(Connector):
    """Connector for a single Legistar client (e.g. ``olympia``)."""

    def __init__(
        self,
        client: str,
        jurisdiction_id: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        fetch_json: Callable[[str, Dict[str, Any]], Any] = _requests_fetch_json,
    ):
        self.client = client
        self.jurisdiction_id = jurisdiction_id or f"{client}-legistar"
        self.base_url = base_url.rstrip("/")
        self._fetch_json = fetch_json

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{self.client}/{path.lstrip('/')}"

    def _paginate(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        skip = 0
        while True:
            page_params = dict(params, **{"$top": PAGE_SIZE, "$skip": skip})
            page = self._fetch_json(self._url(path), page_params)
            if not page:
                break
            results.extend(page)
            if len(page) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
        return results

    def list_bodies(self) -> List[Body]:
        raw_bodies = self._paginate("bodies", {})
        return [parse_body(b, self.jurisdiction_id) for b in raw_bodies]

    def list_meetings(self, since: Optional[datetime] = None) -> List[Meeting]:
        params: Dict[str, Any] = {"$orderby": "EventDate desc"}
        if since is not None:
            params["$filter"] = f"EventDate ge datetime'{since.strftime('%Y-%m-%dT%H:%M:%S')}'"
        raw_events = self._paginate("events", params)
        return [parse_event(e) for e in raw_events]

    def get_items(self, meeting: Meeting) -> List[AgendaItem]:
        raw_items = self._paginate(f"events/{meeting.native_id}/eventitems", {})
        return [parse_event_item(i, meeting.native_id) for i in raw_items]

    def get_documents(self, meeting: Meeting) -> List[Document]:
        return parse_documents(meeting)
