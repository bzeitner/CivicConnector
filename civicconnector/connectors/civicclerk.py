"""CivicClerk connector (Phase 3, Lacey pilot).

Talks to the undocumented-but-real CivicClerk OData v1 API
(``{tenant}.api.civicclerk.com/v1``), verified live against the ``laceywa``
tenant in IdeaFlow idea #32 research entries #80 and #205.

HTTP fetching is injected via ``fetch_json``/``fetch_text`` so the parsing
logic can be exercised offline against the pinned fixtures in
``tests/fixtures/`` without a live network call, matching the Legistar
connector's pattern (Phase 2).

Phase 3 exit-criteria finding — ``GetMeetingItemMinutesVotes`` population
for Lacey (research entry #80's highest-uncertainty question):

    The bound function ``Meetings/GetMeetingItemMinutesVotes(id=<id>)``
    responds HTTP 200, proving the endpoint exists and is callable exactly
    as its ``$metadata`` signature describes. It was called live against
    seven distinct Lacey meetings (City Council, Worksession, Planning
    Commission; five different agendaId/eventId values spanning July-Aug
    2026, both as the event id and as the agendaId) and returned an empty
    ``value: []`` array every time.

    Separately, no GET-accessible path was found to enumerate the
    individual agenda-item ids the function's ``id`` parameter most likely
    expects (``AgendaObjItemsModel.id`` from ``MeetingApiModel.items``):
    ``Meetings(id)`` 404s, ``Meetings?$filter=id eq ...`` 404s, and the
    ``Sections`` entity set that models agenda structure only accepts POST
    (405 on GET), which is outside this API's discoverable read surface.

    **Finding: NO** — ``GetMeetingItemMinutesVotes`` is not confirmed
    populated for Lacey, and more importantly this connector cannot
    currently obtain a valid item id to query it meaningfully through the
    public v1 surface. Per the plan, "vote extraction" is *not* promised
    for CivicClerk/Lacey; this connector never sets ``Vote`` records and
    ``get_items`` returns an empty list rather than guessing, consistent
    with the "return None/empty, never guess" rule. This should be
    revisited if a browser-driven trace of the public portal UI surfaces
    the real item-id addressing (out of scope for this API-only pass).

Documents ARE a first-class win here: ``GetMeetingFileStream(fileId=...,
plainText=true)`` was verified live end-to-end, returning HTTP 200 plain
text for a real agenda PDF — bypassing PDF/OCR extraction entirely, exactly
as research entry #80 predicted.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from civicconnector.connectors.base import Connector
from civicconnector.models import AgendaItem, Body, Document, Meeting

DEFAULT_BASE_URL = "https://laceywa.api.civicclerk.com/v1"
PAGE_SIZE = 100  # not documented; conservative, no evidence of a hard cap like Legistar's 1000


def _requests_fetch_json(url: str, params: Dict[str, Any]) -> Any:
    import requests

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _requests_fetch_text(url: str) -> str:
    import requests

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_body(raw: Dict[str, Any], jurisdiction_id: str) -> Body:
    return Body(
        jurisdiction_id=jurisdiction_id,
        native_id=str(raw["id"]),
        name=raw["categoryDesc"],
        type=None,
    )


def parse_event(raw: Dict[str, Any]) -> Meeting:
    files = raw.get("publishedFiles") or []
    agenda_url = next((f["url"] for f in files if f.get("type") == "Agenda"), None)
    minutes_url = next((f["url"] for f in files if f.get("type") == "Minutes"), None)
    return Meeting(
        body_id=str(raw.get("categoryId")) if raw.get("categoryId") is not None else "",
        native_id=str(raw["id"]),
        starts_at=datetime.fromisoformat(raw["startDateTime"].replace("Z", "+00:00")),
        status=raw.get("isPublished"),
        agenda_url=agenda_url,
        minutes_url=minutes_url,
        video_url=None,
    )


def parse_documents(raw: Dict[str, Any], meeting_native_id: str) -> List[Document]:
    """Documents come from the Event's ``publishedFiles`` list, not a separate
    call — CivicClerk exposes them inline (unlike Legistar's separate agenda/
    minutes URL fields)."""
    docs = []
    for f in raw.get("publishedFiles") or []:
        docs.append(
            Document(
                meeting_id=meeting_native_id,
                kind=(f.get("type") or "unknown").lower().replace(" ", "_"),
                url=f["url"],
                text_source="plain_text_stream" if f.get("fileId") else None,
            )
        )
    return docs


def coverage_table(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-event coverage row: documents found and whether votes data was
    populated (always ``False`` for now — see module docstring finding)."""
    rows = []
    for raw in events:
        files = raw.get("publishedFiles") or []
        rows.append(
            {
                "event_id": raw["id"],
                "documents": len(files),
                "has_agenda_file": any(f.get("type") == "Agenda" for f in files),
                "has_minutes_file": any(f.get("type") == "Minutes" for f in files),
                "items_with_votes": 0,  # GetMeetingItemMinutesVotes: not populated/reachable (see docstring)
            }
        )
    return rows


class CivicClerkConnector(Connector):
    """Connector for a single CivicClerk tenant (e.g. ``laceywa``)."""

    def __init__(
        self,
        tenant: str,
        jurisdiction_id: Optional[str] = None,
        base_url: Optional[str] = None,
        fetch_json: Callable[[str, Dict[str, Any]], Any] = _requests_fetch_json,
        fetch_text: Callable[[str], str] = _requests_fetch_text,
    ):
        self.tenant = tenant
        self.jurisdiction_id = jurisdiction_id or f"{tenant}-civicclerk"
        self.base_url = (base_url or f"https://{tenant}.api.civicclerk.com/v1").rstrip("/")
        self._fetch_json = fetch_json
        self._fetch_text = fetch_text

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _paginate(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        skip = 0
        while True:
            page_params = dict(params, **{"$top": PAGE_SIZE, "$skip": skip})
            page = self._fetch_json(self._url(path), page_params).get("value", [])
            if not page:
                break
            results.extend(page)
            if len(page) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
        return results

    def list_bodies(self) -> List[Body]:
        raw_categories = self._paginate("EventCategories", {})
        return [parse_body(c, self.jurisdiction_id) for c in raw_categories]

    def list_meetings(self, since: Optional[datetime] = None) -> List[Meeting]:
        params: Dict[str, Any] = {"$orderby": "startDateTime desc"}
        if since is not None:
            params["$filter"] = f"startDateTime ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        raw_events = self._paginate("Events", params)
        return [parse_event(e) for e in raw_events]

    def get_items(self, meeting: Meeting) -> List[AgendaItem]:
        """Not supported: no GET-accessible way to list agenda-item ids was
        found for this tenant (see module docstring finding). Returns an
        empty list rather than guessing, per the connector interface's
        "never a guess" rule."""
        return []

    def get_documents(self, meeting: Meeting) -> List[Document]:
        raw_events = self._paginate("Events", {"$filter": f"id eq {meeting.native_id}"})
        if not raw_events:
            return []
        return parse_documents(raw_events[0], meeting.native_id)

    def get_document_text(self, file_id: str) -> str:
        """CivicClerk-specific extra: fetch an agenda/packet file as plain
        text via ``GetMeetingFileStream(fileId=..., plainText=true)``,
        bypassing PDF/OCR entirely. Verified live 2026-08-16."""
        url = self._url(f"Meetings/GetMeetingFileStream(fileId={file_id},plainText=true)")
        return self._fetch_text(url)
