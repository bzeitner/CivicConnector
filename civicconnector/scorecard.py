"""Coverage scorecard & confidence/provenance reporting (Phase 7).

Per IMPLEMENTATION_PLAN.md Phase 7, this computes -- per jurisdiction -- the
four measures the plan asks for (% of meetings detected before they occur,
median lag from meeting to structured action, % of items with a decision,
% with named votes), plus a document-coverage check that feeds the plan's
kill/scope criterion.

Two of the four measures (the two poll-history ones) cannot be computed from
a single point-in-time pull: "detected early" and "lag to structured action"
are both defined relative to *when* something was first observed, which
requires comparing multiple polls over time. Per the "return None, never
guess" rule established in Phase 1 and followed throughout (see
``connectors/civicclerk.py``'s ``items_with_votes: 0`` finding and
``diff.py``'s stateless caller-supplied-history contract), those two
functions return ``None`` rather than a fabricated number when fewer than
two polls are supplied. Like ``diff.py``, this module has no storage layer
of its own: callers supply poll history however they persist it.

The other two measures (% items with a decision, % with named votes) are
computable from a single snapshot and are reported for real against the
pinned fixtures in ``PHASE7_SCORECARD.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from civicconnector.models import ActionSource, AgendaItem, Meeting, Vote


def pct_items_with_decision(items: Sequence[AgendaItem]) -> Optional[float]:
    """Fraction of ``items`` with a recorded decision (``passed`` is not
    ``None``). ``None`` (not ``0.0``) when there are no items to measure --
    absence of data is not the same as a measured 0% rate."""
    if not items:
        return None
    return sum(1 for i in items if i.passed is not None) / len(items)


def pct_items_with_named_votes(items: Sequence[AgendaItem], votes: Sequence[Vote]) -> Optional[float]:
    """Fraction of ``items`` with at least one named ``Vote`` record
    attached (matched on ``Vote.agenda_item_id == AgendaItem.native_id``).

    Distinct from ``AgendaItem.roll_call`` (a flag that a roll-call vote
    occurred): this measures whether the toolkit actually produced
    per-person ``Vote`` records for the item, which as of Phase 7 no
    connector does (see ``PHASE7_SCORECARD.md``) -- Legistar's votes
    endpoint is pinned as a fixture but not yet wired into
    ``LegistarConnector``, and CivicClerk's vote endpoint was found
    unreachable in Phase 3. ``None`` (not ``0.0``) when there are no items
    to measure.
    """
    if not items:
        return None
    item_native_ids_with_votes = {v.agenda_item_id for v in votes}
    return sum(1 for i in items if i.native_id in item_native_ids_with_votes) / len(items)


def pct_meetings_detected_early(
    polls: Sequence[Tuple[datetime, Sequence[Meeting]]],
) -> Optional[float]:
    """Of meetings observed across a caller-supplied sequence of
    ``(poll_timestamp, meetings)`` snapshots, the fraction whose
    earliest-seen poll happened at or before the meeting's ``starts_at``.

    Requires at least two polls (a single snapshot cannot distinguish "seen
    early" from "seen late" -- there is nothing to compare it to); returns
    ``None`` otherwise.
    """
    if len(polls) < 2:
        return None
    first_seen: Dict[str, datetime] = {}
    starts_at: Dict[str, datetime] = {}
    for poll_ts, meetings in sorted(polls, key=lambda p: p[0]):
        for meeting in meetings:
            first_seen.setdefault(meeting.native_id, poll_ts)
            starts_at[meeting.native_id] = meeting.starts_at
    if not first_seen:
        return None
    early = sum(1 for native_id, ts in first_seen.items() if ts <= starts_at[native_id])
    return early / len(first_seen)


@dataclass
class MeetingItemPollHistory:
    """One meeting's ``starts_at`` plus a caller-supplied sequence of
    ``(poll_timestamp, items)`` snapshots of its agenda items over time,
    for measuring lag-to-structured-action."""

    meeting_native_id: str
    starts_at: datetime
    item_polls: Sequence[Tuple[datetime, Sequence[AgendaItem]]]


def median_lag_to_structured_action(
    histories: Sequence[MeetingItemPollHistory],
) -> Optional[timedelta]:
    """Median elapsed time from a meeting's ``starts_at`` to the first poll
    at which one of its items gained a structured action (``action_source``
    other than ``ActionSource.NONE``). Items that never gain a structured
    action do not contribute a lag (they are the numerator of
    ``1 - pct_items_with_decision``, not part of this measure). Requires at
    least two polls per meeting history to be meaningful; meetings with
    fewer are skipped. Returns ``None`` if no lag could be measured at all.
    """
    lags: List[timedelta] = []
    for history in histories:
        if len(history.item_polls) < 2:
            continue
        first_actioned: Dict[str, datetime] = {}
        for poll_ts, items in sorted(history.item_polls, key=lambda p: p[0]):
            for item in items:
                if item.action_source is not ActionSource.NONE:
                    first_actioned.setdefault(item.native_id, poll_ts)
        lags.extend(ts - history.starts_at for ts in first_actioned.values())
    if not lags:
        return None
    return median(lags)


@dataclass
class JurisdictionScorecard:
    jurisdiction_id: str
    n_meetings: int
    n_items: int
    document_coverage: Optional[bool]
    pct_items_with_decision: Optional[float]
    pct_items_with_named_votes: Optional[float]
    pct_meetings_detected_early: Optional[float]
    median_lag_to_structured_action: Optional[timedelta]


def jurisdiction_scorecard(
    jurisdiction_id: str,
    meetings: Sequence[Meeting],
    items: Sequence[AgendaItem],
    votes: Sequence[Vote] = (),
    document_coverage: Optional[bool] = None,
    meeting_polls: Optional[Sequence[Tuple[datetime, Sequence[Meeting]]]] = None,
    item_poll_histories: Optional[Sequence[MeetingItemPollHistory]] = None,
) -> JurisdictionScorecard:
    """Assemble one jurisdiction's scorecard row from whatever inputs are
    available. The two poll-history measures are ``None`` unless the caller
    supplies ``meeting_polls``/``item_poll_histories`` -- a single snapshot
    (``meetings``/``items``) is enough for the other two measures plus
    ``document_coverage``, but not for those."""
    return JurisdictionScorecard(
        jurisdiction_id=jurisdiction_id,
        n_meetings=len(meetings),
        n_items=len(items),
        document_coverage=document_coverage,
        pct_items_with_decision=pct_items_with_decision(items),
        pct_items_with_named_votes=pct_items_with_named_votes(items, votes),
        pct_meetings_detected_early=pct_meetings_detected_early(meeting_polls or []),
        median_lag_to_structured_action=median_lag_to_structured_action(item_poll_histories or []),
    )


def format_scorecard_table(rows: Sequence[JurisdictionScorecard]) -> List[Dict[str, object]]:
    """Render scorecard rows as plain dicts, matching the existing
    per-connector ``coverage_table()`` dict-list convention
    (``connectors/legistar.py``, ``connectors/civicclerk.py``)."""
    return [
        {
            "jurisdiction_id": row.jurisdiction_id,
            "n_meetings": row.n_meetings,
            "n_items": row.n_items,
            "document_coverage": row.document_coverage,
            "pct_items_with_decision": row.pct_items_with_decision,
            "pct_items_with_named_votes": row.pct_items_with_named_votes,
            "pct_meetings_detected_early": row.pct_meetings_detected_early,
            "median_lag_to_structured_action": row.median_lag_to_structured_action,
        }
        for row in rows
    ]


def kill_scope_decision(
    document_coverage_by_jurisdiction: Dict[str, Optional[bool]],
    threshold: float = 0.9,
) -> str:
    """Apply IMPLEMENTATION_PLAN.md Phase 7's kill/scope criterion: if
    document coverage across the pilot cities is at or above ``threshold``
    (default 90%, per the plan), stop building new connectors for a fourth
    platform and invest further effort in the extraction/diff layer
    instead. Jurisdictions with unknown (``None``) coverage count as not
    covered. Returns ``"insufficient_data"`` if no jurisdictions are
    supplied.
    """
    if not document_coverage_by_jurisdiction:
        return "insufficient_data"
    covered = sum(1 for v in document_coverage_by_jurisdiction.values() if v)
    rate = covered / len(document_coverage_by_jurisdiction)
    if rate >= threshold:
        return "stop_new_connectors_invest_extraction"
    return "continue_building_connectors"
