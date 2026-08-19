from copy import deepcopy
from dataclasses import replace
from datetime import datetime

from civicconnector.connectors.civicclerk import parse_event as civicclerk_parse_event
from civicconnector.connectors.legistar import parse_event as legistar_parse_event
from civicconnector.connectors.legistar import parse_event_item
from civicconnector.connectors.municode import parse_meetings_page, row_to_meeting
from civicconnector.diff import (
    AgendaItemChange,
    MeetingChange,
    detect_agenda_changes,
    detect_meeting_changes,
    hash_item,
    hash_meeting,
    hashes_from_items,
    hashes_from_meetings,
)
from civicconnector.models import ActionSource, AgendaItem, Meeting


# --- hash_item / detect_agenda_changes (item-level; Legistar eventitems) ---


def test_hash_item_is_stable_for_identical_content():
    item = AgendaItem(meeting_id="m1", native_id="1", seq=1, title="Approve minutes")
    assert hash_item(item) == hash_item(replace(item))


def test_hash_item_ignores_provenance_fields():
    """action_source/confidence are provenance, not content -- a connector
    backfilling them once minutes are processed must not register as an
    'amended' item on its own."""
    item = AgendaItem(meeting_id="m1", native_id="1", title="Approve minutes")
    backfilled = replace(item, action_source=ActionSource.MINUTES_PDF, confidence=0.5)
    assert hash_item(item) == hash_item(backfilled)


def test_hash_item_changes_when_content_changes():
    item = AgendaItem(meeting_id="m1", native_id="1", title="Approve minutes")
    amended = replace(item, title="Approve minutes as amended")
    assert hash_item(item) != hash_item(amended)


def test_detect_agenda_changes_first_poll_is_all_added():
    items = [AgendaItem(meeting_id="m1", native_id="1", title="Item A")]
    changes = detect_agenda_changes("m1", items, previous_hashes={})
    assert changes == [
        AgendaItemChange(meeting_id="m1", native_id="1", status="added", content_hash=hash_item(items[0]))
    ]


def test_detect_agenda_changes_across_two_polls_legistar_eventitems(legistar_eventitems):
    """Two successive polls of the pinned Olympia eventitems fixture: poll 1
    is the fixture as-is; poll 2 amends one item's title, drops the last item
    (pulled since last posting), and adds one brand-new item."""
    meeting_id = "olympia-7259"
    poll1 = [parse_event_item(raw, meeting_id) for raw in legistar_eventitems]
    assert len(poll1) >= 3  # fixture must have enough rows to exercise all four statuses

    poll2_raw = deepcopy(legistar_eventitems)
    amended_id = str(poll2_raw[0]["EventItemId"])
    dropped_id = str(poll2_raw[-1]["EventItemId"])
    poll2_raw[0]["EventItemTitle"] = (poll2_raw[0].get("EventItemTitle") or "") + " (AMENDED)"
    del poll2_raw[-1]
    poll2_raw.append(
        {
            "EventItemId": 99999999,
            "EventItemAgendaSequence": 999,
            "EventItemAgendaNumber": "99.",
            "EventItemTitle": "Newly added item",
        }
    )
    poll2 = [parse_event_item(raw, meeting_id) for raw in poll2_raw]

    prev_hashes = hashes_from_items(poll1)
    changes = detect_agenda_changes(meeting_id, poll2, prev_hashes)
    by_native_id = {c.native_id: c for c in changes}

    assert by_native_id[amended_id].status == "amended"
    assert by_native_id["99999999"].status == "added"
    assert by_native_id[dropped_id].status == "pulled"
    assert by_native_id[dropped_id].content_hash is None
    unchanged_native_ids = {
        str(raw["EventItemId"]) for raw in legistar_eventitems
    } - {amended_id, dropped_id}
    for native_id in unchanged_native_ids:
        assert by_native_id[native_id].status == "unchanged"


def test_hashes_from_items_round_trips_into_detect_agenda_changes():
    items = [AgendaItem(meeting_id="m1", native_id="1", title="Item A")]
    prev = hashes_from_items(items)
    changes = detect_agenda_changes("m1", items, prev)
    assert changes == [AgendaItemChange(meeting_id="m1", native_id="1", status="unchanged", content_hash=hash_item(items[0]))]


# --- hash_meeting / detect_meeting_changes (meeting-level; all three platforms) ---


def test_detect_meeting_changes_legistar_events(legistar_events):
    """Legistar: a meeting whose agenda file URL changes (a re-posted
    agenda) between two polls is flagged 'changed'."""
    poll1 = [legistar_parse_event(raw) for raw in legistar_events]
    poll2_raw = deepcopy(legistar_events)
    poll2_raw[0]["EventAgendaFile"] = "https://legistar.granicus.com/olympia/meetings/replacement.pdf"
    poll2 = [legistar_parse_event(raw) for raw in poll2_raw]

    prev_hashes = hashes_from_meetings(poll1)
    changes = detect_meeting_changes(poll2, prev_hashes)
    by_native_id = {c.native_id: c for c in changes}

    assert by_native_id[poll1[0].native_id].status == "changed"
    for meeting in poll1[1:]:
        assert by_native_id[meeting.native_id].status == "unchanged"


def test_detect_meeting_changes_civicclerk_events(civicclerk_events):
    """CivicClerk: get_items() always returns [] (Phase 3 finding), so
    meeting-level diff is the only agenda-revision signal available -- a new
    publishedFiles agenda URL between polls must be flagged 'changed'."""
    events = civicclerk_events["value"]
    poll1 = [civicclerk_parse_event(raw) for raw in events]
    poll2_raw = deepcopy(events)
    poll2_raw[0]["publishedFiles"] = (poll2_raw[0].get("publishedFiles") or []) + [
        {"type": "Agenda", "url": "https://laceywa.api.civicclerk.com/v1/newly-posted-agenda.pdf"}
    ]
    poll2 = [civicclerk_parse_event(raw) for raw in poll2_raw]

    prev_hashes = hashes_from_meetings(poll1)
    changes = detect_meeting_changes(poll2, prev_hashes)
    by_native_id = {c.native_id: c for c in changes}

    assert by_native_id[poll1[0].native_id].status == "changed"
    for meeting in poll1[1:]:
        assert by_native_id[meeting.native_id].status == "unchanged"


def test_detect_meeting_changes_municode_meetings(municode_meetings_page):
    """Municode: get_items() always returns [] (no item-level agenda data,
    Phase 4), so meeting-level diff is the only agenda-revision signal --
    a new agenda_url between polls (a re-posted PDF) must be flagged
    'changed'."""
    rows = parse_meetings_page(municode_meetings_page)
    poll1 = [m for m in (row_to_meeting(r, "tumwater-wa-municode") for r in rows) if m]
    assert len(poll1) >= 2

    poll2 = deepcopy(poll1)
    poll2[0] = replace(poll2[0], agenda_url="https://mccmeetings.blob.core.usgovcloudapi.net/tumwater-pubu/replacement.pdf")

    prev_hashes = hashes_from_meetings(poll1)
    changes = detect_meeting_changes(poll2, prev_hashes)
    by_native_id = {c.native_id: c for c in changes}

    assert by_native_id[poll1[0].native_id].status == "changed"
    for meeting in poll1[1:]:
        assert by_native_id[meeting.native_id].status == "unchanged"


def test_detect_meeting_changes_first_poll_is_all_new():
    meeting = Meeting(body_id="b1", native_id="m1", starts_at=datetime(2026, 1, 1))
    changes = detect_meeting_changes([meeting], previous_hashes={})
    assert changes == [MeetingChange(native_id="m1", status="new", content_hash=hash_meeting(meeting))]


def test_hash_meeting_is_stable_for_identical_content():
    meeting = Meeting(body_id="b1", native_id="m1", starts_at=datetime(2026, 1, 1))
    assert hash_meeting(meeting) == hash_meeting(replace(meeting))


def test_detect_meeting_changes_flags_stable_url_content_revision():
    """Regression for PR #7 review (idea #32, research entry #287): a
    reposted agenda whose bytes change at a stable agenda_url/status (e.g.
    Municode, where document hashing is the existing change-detection
    primitive) must be flagged 'changed', not misclassified as
    'unchanged' just because the URL and status didn't move."""
    m1 = Meeting(
        body_id="b1",
        native_id="m1",
        starts_at=datetime(2026, 1, 1),
        agenda_url="https://example.test/agenda.pdf",
        status="Final",
        content_hash="old-bytes",
    )
    m2 = replace(m1, content_hash="new-bytes")

    prev_hashes = hashes_from_meetings([m1])
    changes = detect_meeting_changes([m2], prev_hashes)

    assert changes == [MeetingChange(native_id="m1", status="changed", content_hash=hash_meeting(m2))]
