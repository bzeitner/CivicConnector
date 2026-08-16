"""Contract tests (Phase 1).

Pin the exact JSON shapes returned by the undocumented/unversioned Legistar
and CivicClerk APIs, captured live against olympia.legistar.com and
laceywa.civicclerk.com. These endpoints have no published schema guarantee
(research entry #80), so these tests exist to fail loudly on upstream drift
rather than let a silent field rename or removal corrupt downstream data.

Fixtures were captured live on 2026-08-15/16 against:
  - https://webapi.legistar.com/v1/olympia/events
  - https://webapi.legistar.com/v1/olympia/events/{id}/eventitems
  - https://webapi.legistar.com/v1/olympia/eventitems/{id}/votes
  - https://webapi.legistar.com/v1/olympia/matters/{id}/histories
  - https://laceywa.api.civicclerk.com/v1/Events
"""


def test_legistar_events_shape(legistar_events):
    assert isinstance(legistar_events, list)
    assert legistar_events, "fixture must contain at least one event"
    event = legistar_events[0]
    required_fields = {
        "EventId",
        "EventBodyId",
        "EventBodyName",
        "EventDate",
        "EventAgendaStatusName",
        "EventMinutesStatusName",
        "EventAgendaFile",
        "EventMinutesFile",
        "EventInSiteURL",
        "EventItems",
    }
    assert required_fields <= event.keys()


def test_legistar_eventitems_shape(legistar_eventitems):
    assert isinstance(legistar_eventitems, list)
    assert legistar_eventitems
    item = legistar_eventitems[0]
    required_fields = {
        "EventItemId",
        "EventItemEventId",
        "EventItemAgendaSequence",
        "EventItemAgendaNumber",
        "EventItemActionId",
        "EventItemActionName",
        "EventItemPassedFlag",
        "EventItemPassedFlagName",
        "EventItemRollCallFlag",
        "EventItemMatterId",
    }
    assert required_fields <= item.keys()


def test_legistar_eventitems_matter_id_links_to_histories(
    legistar_eventitems, legistar_matter_histories
):
    """The one item with a MatterId in the fixture should resolve via the
    matters/{id}/histories endpoint pinned in legistar_matter_histories.json."""
    items_with_matter = [i for i in legistar_eventitems if i.get("EventItemMatterId")]
    assert items_with_matter, "fixture expected to contain at least one matter-linked item"
    assert legistar_matter_histories, "matter histories fixture must not be empty"
    history = legistar_matter_histories[0]
    assert history["MatterHistoryEventId"] == items_with_matter[0]["EventItemEventId"]


def test_legistar_votes_shape_is_list(legistar_votes):
    # Coverage caveat from research entry #80, reconfirmed live: named vote
    # rosters are frequently empty even on items with a recorded action.
    # The contract is "always a list", not "always populated".
    assert isinstance(legistar_votes, list)


def test_civicclerk_events_shape(civicclerk_events):
    assert isinstance(civicclerk_events, dict)
    assert "value" in civicclerk_events
    events = civicclerk_events["value"]
    assert events, "fixture must contain at least one event"
    event = events[0]
    required_fields = {
        "id",
        "eventName",
        "startDateTime",
        "categoryName",
        "agendaId",
        "isPublished",
        "mediaSourcePath",
        "youtubeVideoId",
    }
    assert required_fields <= event.keys()
