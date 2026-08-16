"""Municode connector (Phase 4, Tumwater pilot).

Tumwater's meeting portal (``tumwater-wa.municodemeetings.com``) is a
Drupal/CivicPlus site with **no discovered JSON/API surface** (confirmed
live in IdeaFlow idea #32 research entry #80) — unlike Legistar and
CivicClerk, this connector is HTML+PDF acquisition, the tier-3 mode the
plan expects to break most often. Its HTML-parsing assumptions are isolated
behind the shared four-method :class:`Connector` interface so breakage here
doesn't propagate to the other connectors.

Live-verified 2026-08-16 (research entry #80 predates this and used the
literal path ``/meetings3?page=N``; that path now 301-redirects to
``/?page=N`` with identical content — ``requests`` follows the redirect
transparently, so the connector still requests ``/meetings3`` as documented
in the plan):

- ``GET /meetings3?page=0`` -> 301 -> ``GET /?page=0`` -> HTTP 200, a
  "Meetings Directory" table (25 rows/page) with Date, Meeting (body name),
  Agenda/Agenda Packet/Minutes PDF links (on
  ``mccmeetings.blob.core.usgovcloudapi.net/tumwater-pubu/...``), and a
  "View Details" link of the form ``/bc-<code>/page/<slug>`` — the ``bc-*``
  body-code enumeration the plan calls for.
- ``robots.txt`` sets ``Crawl-delay: 15`` — enforced here via
  :meth:`MunicodeConnector._throttle` before every HTTP request (HTML page
  or PDF download), not just documented.
- No usable body-enumeration API exists independent of the meetings table
  (the page also carries a numeric "microsite" filter dropdown, but its ids
  live in a different id space than the ``bc-*`` codes on meeting rows and
  correlating the two would require an extra, unverified request per body).
  So ``list_bodies()`` derives bodies from ``bc-*`` codes actually observed
  in the polled meetings window, not from that dropdown — reporting what
  was seen rather than guessing a mapping, per the connector interface's
  extraction rule.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from civicconnector.connectors.base import Connector
from civicconnector.models import AgendaItem, Body, Document, Meeting

DEFAULT_BASE_URL = "https://tumwater-wa.municodemeetings.com"
CRAWL_DELAY_SECONDS = 15.0  # robots.txt: "Crawl-delay: 15", verified live 2026-08-16
# Identifying UA with contact info, per the plan's politeness requirement.
# Verified live 2026-08-16: this site's WAF resets the connection (no HTTP
# response at all) for any User-Agent containing a "github.com" URL,
# regardless of "Bot" in the product token -- a bare project/contact string
# works. Keep the UA free of full repo URLs if this connector is touched.
USER_AGENT = "CivicConnectorBot/0.1 (project: CivicConnector; contact: bzeitner@gmail.com)"

_ROW_RE = re.compile(r'<tr class="(?:odd|even)[^"]*">(.*?)</tr>', re.S)
_DATE_RE = re.compile(r'content="([^"]+)"')
_TITLE_RE = re.compile(r'views-field-title"\s+data-th="Meeting">\s*(.*?)\s*</td>', re.S)
_AGENDA_CELL_RE = re.compile(r'views-field-field-agendas"\s+data-th="Agenda">(.*?)</td>', re.S)
_PACKET_CELL_RE = re.compile(r'views-field-field-packets"\s+data-th="Agenda Packet">(.*?)</td>', re.S)
_MINUTES_CELL_RE = re.compile(r'views-field-field-minutes"\s+data-th="Minutes">(.*?)</td>', re.S)
_VIEW_CELL_RE = re.compile(r'views-field-view-node"\s+data-th="View">(.*?)</td>', re.S)
_PDF_HREF_RE = re.compile(r'href="([^"]+\.pdf)"')
_BC_HREF_RE = re.compile(r'href="/(bc-[a-z0-9\-]+)/page/([a-z0-9\-]+)"')
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


def _first_pdf_href(cell_html: str) -> Optional[str]:
    m = _PDF_HREF_RE.search(cell_html)
    return m.group(1) if m else None


def _requests_fetch_html(url: str, params: Dict[str, Any]) -> str:
    import requests

    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def _requests_fetch_bytes(url: str) -> bytes:
    import requests

    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    return response.content


def parse_meeting_row(row_html: str) -> Dict[str, Optional[str]]:
    """Parse one ``<tr>`` of the Meetings Directory table into a flat dict.

    Returns ``None`` for any field the row doesn't contain, rather than
    guessing — the row-to-Meeting/Document mapping functions below decide
    what to do with missing fields.
    """
    date_m = _DATE_RE.search(row_html)
    title_m = _TITLE_RE.search(row_html)
    agenda_cell = _AGENDA_CELL_RE.search(row_html)
    packet_cell = _PACKET_CELL_RE.search(row_html)
    minutes_cell = _MINUTES_CELL_RE.search(row_html)
    view_cell = _VIEW_CELL_RE.search(row_html)

    bc_code = slug = None
    if view_cell:
        bc_m = _BC_HREF_RE.search(view_cell.group(1))
        if bc_m:
            bc_code, slug = bc_m.group(1), bc_m.group(2)

    return {
        "starts_at": date_m.group(1) if date_m else None,
        "title": _strip_tags(title_m.group(1)) if title_m else None,
        "agenda_url": _first_pdf_href(agenda_cell.group(1)) if agenda_cell else None,
        "packet_url": _first_pdf_href(packet_cell.group(1)) if packet_cell else None,
        "minutes_url": _first_pdf_href(minutes_cell.group(1)) if minutes_cell else None,
        "bc_code": bc_code,
        "slug": slug,
    }


def parse_meetings_page(html: str) -> List[Dict[str, Optional[str]]]:
    """Parse every row of a Meetings Directory page (one ``page=N`` fetch)."""
    return [parse_meeting_row(m.group(1)) for m in _ROW_RE.finditer(html)]


def row_to_meeting(row: Dict[str, Optional[str]], jurisdiction_id: str) -> Optional[Meeting]:
    """Build a Meeting from a parsed row, or ``None`` if the row lacks the
    fields needed to identify one (date + body code + detail slug)."""
    if not row.get("starts_at") or not row.get("bc_code") or not row.get("slug"):
        return None
    return Meeting(
        body_id=row["bc_code"],
        native_id=row["slug"],
        starts_at=datetime.fromisoformat(row["starts_at"]),
        agenda_url=row.get("agenda_url"),
        minutes_url=row.get("minutes_url"),
    )


def row_to_documents(row: Dict[str, Optional[str]], meeting_native_id: str) -> List[Document]:
    docs = []
    if row.get("agenda_url"):
        docs.append(Document(meeting_id=meeting_native_id, kind="agenda", url=row["agenda_url"]))
    if row.get("packet_url"):
        docs.append(Document(meeting_id=meeting_native_id, kind="agenda_packet", url=row["packet_url"]))
    if row.get("minutes_url"):
        docs.append(Document(meeting_id=meeting_native_id, kind="minutes", url=row["minutes_url"]))
    return docs


def rows_to_bodies(rows: List[Dict[str, Optional[str]]], jurisdiction_id: str) -> List[Body]:
    """Bodies observed in a set of parsed rows, deduped by ``bc-*`` code.

    Not a canonical enumeration of every Tumwater body — only those with a
    meeting in the polled window. See module docstring for why this
    connector doesn't use the page's numeric "microsite" filter dropdown
    instead.
    """
    seen: Dict[str, Body] = {}
    for row in rows:
        bc_code, title = row.get("bc_code"), row.get("title")
        if bc_code and title and bc_code not in seen:
            seen[bc_code] = Body(
                jurisdiction_id=jurisdiction_id,
                native_id=bc_code,
                name=title,
                type="committee",
            )
    return list(seen.values())


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class DocumentChange:
    """Result of comparing one Document's current content hash to the last
    known hash for its URL. ``status`` is ``"new"`` (no prior hash),
    ``"changed"`` (hash differs), or ``"unchanged"``."""

    url: str
    kind: str
    status: str
    sha256: str


def detect_changes(
    documents: List[Document],
    previous_hashes: Dict[str, str],
    fetch_bytes: Callable[[str], bytes],
) -> List[DocumentChange]:
    """Hash each document's current bytes and compare to ``previous_hashes``
    (a ``{url: sha256}`` map from the last poll, supplied by the caller —
    this connector holds no persistent state). This is Phase 4's core
    deliverable: flagging a new or updated agenda PDF without guessing at
    its content from metadata alone."""
    changes = []
    for doc in documents:
        digest = hash_bytes(fetch_bytes(doc.url))
        prior = previous_hashes.get(doc.url)
        if prior is None:
            status = "new"
        elif prior != digest:
            status = "changed"
        else:
            status = "unchanged"
        changes.append(DocumentChange(url=doc.url, kind=doc.kind, status=status, sha256=digest))
    return changes


class MunicodeConnector(Connector):
    """Connector for a single Municode/CivicPlus Drupal meetings portal
    (e.g. Tumwater)."""

    def __init__(
        self,
        jurisdiction_id: str = "tumwater-wa-municode",
        base_url: str = DEFAULT_BASE_URL,
        fetch_html: Callable[[str, Dict[str, Any]], str] = _requests_fetch_html,
        fetch_bytes: Callable[[str], bytes] = _requests_fetch_bytes,
        crawl_delay: float = CRAWL_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.jurisdiction_id = jurisdiction_id
        self.base_url = base_url.rstrip("/")
        self._fetch_html = fetch_html
        self._fetch_bytes = fetch_bytes
        self.crawl_delay = crawl_delay
        self._sleep = sleep
        self._last_request_at: Optional[float] = None
        self._documents_by_meeting: Dict[str, List[Document]] = {}

    def _throttle(self) -> None:
        """Block until at least ``crawl_delay`` seconds have passed since
        the last request, honoring robots.txt's Crawl-delay directive on
        every HTML page fetch and every PDF download."""
        if self._last_request_at is not None:
            remaining = self.crawl_delay - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = time.monotonic()

    def _fetch_page(self, page: int) -> str:
        self._throttle()
        return self._fetch_html(f"{self.base_url}/meetings3", {"page": page})

    def _fetch_document_bytes(self, url: str) -> bytes:
        self._throttle()
        return self._fetch_bytes(url)

    def list_bodies(self) -> List[Body]:
        rows = parse_meetings_page(self._fetch_page(0))
        return rows_to_bodies(rows, self.jurisdiction_id)

    def list_meetings(self, since: Optional[datetime] = None, max_pages: int = 20) -> List[Meeting]:
        """Page ``/meetings3?page=N`` (most-recent-first) until either a
        page comes back empty or (when ``since`` is given) a full page's
        oldest row is already older than ``since``. Without a ``since``
        cutoff, only page 0 is fetched — an unbounded crawl of full meeting
        history isn't polite against a 15s-per-request budget and isn't
        needed for change detection, this phase's exit criterion."""
        all_rows: List[Dict[str, Optional[str]]] = []
        page = 0
        while page < max_pages:
            rows = parse_meetings_page(self._fetch_page(page))
            if not rows:
                break
            all_rows.extend(rows)
            if since is None:
                break
            dated = [r for r in rows if r.get("starts_at")]
            if dated and min(datetime.fromisoformat(r["starts_at"]) for r in dated) < since:
                break
            page += 1

        meetings: List[Meeting] = []
        documents_by_meeting: Dict[str, List[Document]] = {}
        for row in all_rows:
            meeting = row_to_meeting(row, self.jurisdiction_id)
            if meeting is None:
                continue
            if since is not None and meeting.starts_at < since:
                continue
            meetings.append(meeting)
            documents_by_meeting[meeting.native_id] = row_to_documents(row, meeting.native_id)

        self._documents_by_meeting = documents_by_meeting
        return meetings

    def get_items(self, meeting: Meeting) -> List[AgendaItem]:
        # The Drupal HTML portal exposes no item-level agenda data outside
        # the PDF agenda/packet documents. Parsing those PDFs for structured
        # items is out of scope for this phase (reserved for a future
        # minutes/PDF extraction phase per IMPLEMENTATION_PLAN.md). Return
        # [] rather than guessing, per the connector interface's rule.
        return []

    def get_documents(self, meeting: Meeting) -> List[Document]:
        cached = self._documents_by_meeting.get(meeting.native_id)
        if cached is not None:
            return cached
        # Fallback for a Meeting built independently of list_meetings():
        # only agenda/minutes are recoverable from the schema's own fields
        # (Document schema has no dedicated packet_url field).
        docs = []
        if meeting.agenda_url:
            docs.append(Document(meeting_id=meeting.native_id, kind="agenda", url=meeting.agenda_url))
        if meeting.minutes_url:
            docs.append(Document(meeting_id=meeting.native_id, kind="minutes", url=meeting.minutes_url))
        return docs
