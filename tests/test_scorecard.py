"""Phase 7: coverage scorecard & confidence/provenance reporting tests."""

from datetime import datetime, timedelta

from civicconnector.connectors.legistar import parse_event_item
from civicconnector.models import ActionSource, AgendaItem, Meeting, Vote
from civicconnector.scorecard import (
    MeetingItemPollHistory,
    format_scorecard_table,
    jurisdiction_scorecard,
    kill_scope_decision,
    median_lag_to_structured_action,
    pct_items_with_decision,
    pct_items_with_named_votes,
    pct_meetings_detected_early,
)


def _item(native_id, passed=None, action_source=ActionSource.NONE):
    return AgendaItem(meeting_id="m1", native_id=native_id, passed=passed, action_source=action_source)


def _meeting(native_id, starts_at):
    return Meeting(body_id="b1", native_id=native_id, starts_at=starts_at)


# -- single-snapshot measures --------------------------------------------


def test_pct_items_with_decision_none_when_no_items():
    assert pct_items_with_decision([]) is None


def test_pct_items_with_decision_counts_non_none_passed():
    items = [_item("1", passed=True), _item("2", passed=False), _item("3", passed=None)]
    assert pct_items_with_decision(items) == 2 / 3


def test_pct_items_with_decision_against_legistar_fixture_matches_research_entry_80(
    legistar_eventitems,
):
    items = [parse_event_item(i, meeting_native_id="7259") for i in legistar_eventitems]
    expected = sum(1 for i in items if i.passed is not None) / len(items)
    assert pct_items_with_decision(items) == expected


def test_pct_items_with_named_votes_none_when_no_items():
    assert pct_items_with_named_votes([], []) is None


def test_pct_items_with_named_votes_matches_on_agenda_item_id():
    items = [_item("1"), _item("2"), _item("3")]
    votes = [Vote(agenda_item_id="1", person="A", vote_value="aye")]
    assert pct_items_with_named_votes(items, votes) == 1 / 3


def test_pct_items_with_named_votes_is_zero_when_no_connector_produces_votes():
    """As of Phase 7, no connector wires the Vote model up (Legistar's votes
    fixture/endpoint is pinned but not parsed into Vote records; CivicClerk's
    vote endpoint was found unreachable in Phase 3). This is the documented,
    honest state of the toolkit, not a bug in this measure."""
    items = [_item("1"), _item("2")]
    assert pct_items_with_named_votes(items, []) == 0.0


# -- poll-history measures -------------------------------------------------


def test_pct_meetings_detected_early_none_with_fewer_than_two_polls():
    meeting = _meeting("1", datetime(2026, 8, 11, 18, 0))
    assert pct_meetings_detected_early([]) is None
    assert pct_meetings_detected_early([(datetime(2026, 8, 10), [meeting])]) is None


def test_pct_meetings_detected_early_counts_first_seen_before_starts_at():
    starts_at = datetime(2026, 8, 11, 18, 0)
    meeting = _meeting("1", starts_at)
    late_meeting = _meeting("2", starts_at)
    polls = [
        (starts_at - timedelta(days=2), [meeting]),  # meeting 1: seen 2 days early
        (starts_at + timedelta(hours=1), [meeting, late_meeting]),  # meeting 2: first seen after it started
    ]
    assert pct_meetings_detected_early(polls) == 0.5


def test_median_lag_to_structured_action_none_with_no_qualifying_history():
    assert median_lag_to_structured_action([]) is None
    starts_at = datetime(2026, 8, 11, 18, 0)
    single_poll = MeetingItemPollHistory(
        meeting_native_id="1",
        starts_at=starts_at,
        item_polls=[(starts_at, [_item("a", action_source=ActionSource.API)])],
    )
    assert median_lag_to_structured_action([single_poll]) is None


def test_median_lag_to_structured_action_measures_time_to_first_structured_poll():
    starts_at = datetime(2026, 8, 11, 18, 0)
    history = MeetingItemPollHistory(
        meeting_native_id="1",
        starts_at=starts_at,
        item_polls=[
            (starts_at, [_item("a"), _item("b")]),  # no action yet at meeting time
            (
                starts_at + timedelta(days=1),
                [_item("a", action_source=ActionSource.API), _item("b")],
            ),
            (
                starts_at + timedelta(days=3),
                [
                    _item("a", action_source=ActionSource.API),
                    _item("b", action_source=ActionSource.MINUTES_PDF),
                ],
            ),
        ],
    )
    # item "a" first gained a structured action 1 day after starts_at,
    # item "b" 3 days after -- median of [1 day, 3 days] is 2 days.
    assert median_lag_to_structured_action([history]) == timedelta(days=2)


# -- assembled scorecard row -----------------------------------------------


def test_jurisdiction_scorecard_reports_none_for_unmeasured_poll_history_fields():
    items = [_item("1", passed=True), _item("2")]
    row = jurisdiction_scorecard(
        "lacey-civicclerk",
        meetings=[_meeting("1", datetime(2026, 8, 11))],
        items=[],
        votes=[],
        document_coverage=True,
    )
    assert row.n_items == 0
    assert row.pct_items_with_decision is None
    assert row.pct_items_with_named_votes is None
    assert row.pct_meetings_detected_early is None
    assert row.median_lag_to_structured_action is None
    assert row.document_coverage is True


def test_format_scorecard_table_shape():
    row = jurisdiction_scorecard(
        "olympia-legistar",
        meetings=[_meeting("1", datetime(2026, 8, 11))],
        items=[_item("1", passed=True)],
        document_coverage=True,
    )
    table = format_scorecard_table([row])
    assert table == [
        {
            "jurisdiction_id": "olympia-legistar",
            "n_meetings": 1,
            "n_items": 1,
            "document_coverage": True,
            "pct_items_with_decision": 1.0,
            "pct_items_with_named_votes": 0.0,
            "pct_meetings_detected_early": None,
            "median_lag_to_structured_action": None,
        }
    ]


# -- kill/scope decision ----------------------------------------------------


def test_kill_scope_decision_insufficient_data():
    assert kill_scope_decision({}) == "insufficient_data"


def test_kill_scope_decision_stops_at_or_above_threshold():
    coverage = {"olympia-legistar": True, "lacey-civicclerk": True, "tumwater-municode": True}
    assert kill_scope_decision(coverage) == "stop_new_connectors_invest_extraction"


def test_kill_scope_decision_continues_below_threshold():
    coverage = {"olympia-legistar": True, "lacey-civicclerk": True, "tumwater-municode": False}
    assert kill_scope_decision(coverage) == "continue_building_connectors"


def test_kill_scope_decision_treats_none_as_not_covered():
    coverage = {"olympia-legistar": True, "lacey-civicclerk": None, "tumwater-municode": True}
    assert kill_scope_decision(coverage) == "continue_building_connectors"
