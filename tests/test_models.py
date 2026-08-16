from datetime import datetime, timezone

from civicconnector.models import (
    ActionSource,
    AgendaItem,
    Body,
    Document,
    Jurisdiction,
    Meeting,
    Vote,
)


def test_jurisdiction_construction():
    j = Jurisdiction(
        id="olympia-wa",
        name="City of Olympia",
        platform="legistar",
        base_url="https://webapi.legistar.com/v1/olympia",
        tz="America/Los_Angeles",
    )
    assert j.platform == "legistar"
    assert j.poll_policy is None


def test_meeting_from_legistar_event(legistar_events):
    event = legistar_events[0]
    meeting = Meeting(
        body_id=str(event["EventBodyId"]),
        native_id=str(event["EventId"]),
        starts_at=datetime.fromisoformat(event["EventDate"]),
        status=event["EventAgendaStatusName"],
        agenda_url=event["EventAgendaFile"],
        minutes_url=event["EventMinutesFile"],
    )
    assert meeting.native_id == str(event["EventId"])
    assert meeting.status == "Final"


def test_agenda_item_defaults_to_no_action_source():
    item = AgendaItem(meeting_id="m1", native_id="101697")
    assert item.action_source == ActionSource.NONE
    assert item.passed is None


def test_agenda_item_from_legistar_matter_history(legistar_matter_histories):
    history = legistar_matter_histories[0]
    item = AgendaItem(
        meeting_id=str(history["MatterHistoryEventId"]),
        native_id=str(history["MatterHistoryId"]),
        number=history["MatterHistoryAgendaNumber"],
        action_name=history["MatterHistoryActionName"],
        action_source=ActionSource.API,
    )
    assert item.action_name == "completed"
    assert item.action_source is ActionSource.API


def test_vote_construction():
    v = Vote(agenda_item_id="i1", person="Councilmember X", vote_value="Aye", source="api")
    assert v.vote_value == "Aye"


def test_document_construction():
    d = Document(
        meeting_id="m1",
        kind="agenda",
        url="https://legistar.granicus.com/olympia/meetings/2026/8/6949_A.pdf",
        retrieved_at=datetime.now(timezone.utc),
    )
    assert d.kind == "agenda"


def test_body_and_all_models_importable():
    Body(jurisdiction_id="olympia-wa", native_id="138", name="City Council")
