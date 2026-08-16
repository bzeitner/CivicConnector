import hashlib

from civicconnector.connectors.municode import (
    DocumentChange,
    MunicodeConnector,
    detect_changes,
    hash_bytes,
    parse_meeting_row,
    parse_meetings_page,
    row_to_documents,
    row_to_meeting,
    rows_to_bodies,
)
from civicconnector.models import Body, Document, Meeting


# --- parsing (pinned live fixture: tests/fixtures/municode_meetings_page.html) ---


def test_parse_meetings_page_returns_all_rows(municode_meetings_page):
    rows = parse_meetings_page(municode_meetings_page)
    assert len(rows) == 5  # trimmed fixture keeps the first 5 live rows


def test_parse_meeting_row_extracts_expected_fields(municode_meetings_page):
    rows = parse_meetings_page(municode_meetings_page)
    row = rows[0]
    assert row["starts_at"] == "2026-08-20T11:00:00-07:00"
    assert row["title"] == "Public Works Committee"
    assert row["bc_code"] == "bc-pw"
    assert row["slug"] == "public-works-committee-87"
    assert row["agenda_url"] == (
        "https://mccmeetings.blob.core.usgovcloudapi.net/tumwater-pubu/"
        "MEET-Agenda-e5993d899da74002884cd68fd8ffb443.pdf"
    )
    assert row["packet_url"] == (
        "https://mccmeetings.blob.core.usgovcloudapi.net/tumwater-pubu/"
        "MEET-Packet-e5993d899da74002884cd68fd8ffb443.pdf"
    )
    assert row["minutes_url"] is None  # not yet held, matches the live row


def test_parse_meeting_row_handles_missing_cells():
    row = parse_meeting_row('<tr class="odd"><td>nothing useful here</td></tr>')
    assert row == {
        "starts_at": None,
        "title": None,
        "agenda_url": None,
        "packet_url": None,
        "minutes_url": None,
        "bc_code": None,
        "slug": None,
    }


# --- row -> schema mapping ---


def test_row_to_meeting_builds_meeting(municode_meetings_page):
    row = parse_meetings_page(municode_meetings_page)[0]
    meeting = row_to_meeting(row, "tumwater-wa-municode")
    assert isinstance(meeting, Meeting)
    assert meeting.body_id == "bc-pw"
    assert meeting.native_id == "public-works-committee-87"
    assert meeting.agenda_url == row["agenda_url"]


def test_row_to_meeting_returns_none_without_identifying_fields():
    assert row_to_meeting({"starts_at": None, "bc_code": "bc-cc", "slug": "x"}, "j") is None
    assert row_to_meeting({"starts_at": "2026-01-01T00:00:00", "bc_code": None, "slug": "x"}, "j") is None


def test_row_to_documents_includes_agenda_packet_and_minutes():
    row = {
        "agenda_url": "https://example.test/a.pdf",
        "packet_url": "https://example.test/p.pdf",
        "minutes_url": "https://example.test/m.pdf",
    }
    docs = row_to_documents(row, "meeting-1")
    kinds = {d.kind for d in docs}
    assert kinds == {"agenda", "agenda_packet", "minutes"}
    assert all(isinstance(d, Document) for d in docs)


def test_rows_to_bodies_dedupes_by_bc_code(municode_meetings_page):
    rows = parse_meetings_page(municode_meetings_page)
    bodies = rows_to_bodies(rows, "tumwater-wa-municode")
    assert all(isinstance(b, Body) for b in bodies)
    codes = [b.native_id for b in bodies]
    assert len(codes) == len(set(codes))
    assert "bc-pw" in codes
    assert "bc-cc" in codes


# --- change detection (Phase 4's core deliverable) ---


def test_detect_changes_flags_new_changed_and_unchanged():
    doc_a = Document(meeting_id="m1", kind="agenda", url="https://example.test/a.pdf")
    doc_b = Document(meeting_id="m1", kind="agenda", url="https://example.test/b.pdf")
    doc_c = Document(meeting_id="m1", kind="agenda", url="https://example.test/c.pdf")

    content = {
        doc_a.url: b"agenda v2 content",
        doc_b.url: b"agenda v1 unchanged",
        doc_c.url: b"brand new agenda",
    }

    def fake_fetch_bytes(url):
        return content[url]

    previous_hashes = {
        doc_a.url: hashlib.sha256(b"agenda v1 content").hexdigest(),  # differs -> changed
        doc_b.url: hash_bytes(content[doc_b.url]),  # matches -> unchanged
        # doc_c has no prior hash -> new
    }

    changes = detect_changes([doc_a, doc_b, doc_c], previous_hashes, fake_fetch_bytes)
    by_url = {c.url: c for c in changes}
    assert all(isinstance(c, DocumentChange) for c in changes)
    assert by_url[doc_a.url].status == "changed"
    assert by_url[doc_b.url].status == "unchanged"
    assert by_url[doc_c.url].status == "new"
    assert by_url[doc_c.url].sha256 == hash_bytes(content[doc_c.url])


def test_hash_bytes_is_sha256_hex():
    assert hash_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()


# --- connector end-to-end against fixture, with throttling verified ---


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _fetch_html_factory(pages):
    calls = []

    def fetch_html(url, params):
        calls.append((url, params))
        return pages[params["page"]]

    fetch_html.calls = calls
    return fetch_html


def test_connector_list_bodies_and_list_meetings_use_fixture(municode_meetings_page):
    fetch_html = _fetch_html_factory({0: municode_meetings_page})
    connector = MunicodeConnector(fetch_html=fetch_html, sleep=lambda s: None)

    bodies = connector.list_bodies()
    assert bodies and all(isinstance(b, Body) for b in bodies)

    meetings = connector.list_meetings()
    assert meetings and all(isinstance(m, Meeting) for m in meetings)
    assert len(fetch_html.calls) == 2  # one page for list_bodies, one for list_meetings

    docs = connector.get_documents(meetings[0])
    assert docs and all(isinstance(d, Document) for d in docs)

    # HTML/PDF-only platform: item-level extraction is out of scope, and the
    # connector says so explicitly rather than guessing.
    assert connector.get_items(meetings[0]) == []


def test_connector_list_meetings_stops_paging_without_since(municode_meetings_page):
    fetch_html = _fetch_html_factory({0: municode_meetings_page, 1: municode_meetings_page})
    connector = MunicodeConnector(fetch_html=fetch_html, sleep=lambda s: None)
    connector.list_meetings()
    assert len(fetch_html.calls) == 1  # unbounded since=None fetches page 0 only


def test_connector_throttles_between_requests(municode_meetings_page):
    clock = _FakeClock()
    fetch_html = _fetch_html_factory({0: municode_meetings_page})
    connector = MunicodeConnector(
        fetch_html=fetch_html,
        sleep=clock.sleep,
    )
    connector._last_request_at = None
    import civicconnector.connectors.municode as municode_module

    original_monotonic = municode_module.time.monotonic
    municode_module.time.monotonic = clock.monotonic
    try:
        connector.list_bodies()
        first_time = clock.now
        connector._fetch_page(0)  # second request should wait out the crawl delay
        assert clock.now - first_time >= connector.crawl_delay
    finally:
        municode_module.time.monotonic = original_monotonic


def test_connector_get_documents_falls_back_to_meeting_fields_when_uncached():
    connector = MunicodeConnector(sleep=lambda s: None)
    meeting = Meeting(
        body_id="bc-cc",
        native_id="standalone-meeting",
        starts_at=__import__("datetime").datetime(2026, 1, 1),
        agenda_url="https://example.test/a.pdf",
        minutes_url="https://example.test/m.pdf",
    )
    docs = connector.get_documents(meeting)
    kinds = {d.kind for d in docs}
    assert kinds == {"agenda", "minutes"}
