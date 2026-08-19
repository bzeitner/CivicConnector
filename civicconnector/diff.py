"""Change-detection / agenda-diff service (Phase 6).

Generalizes the document-level hash-and-compare primitive introduced for
Municode in Phase 4 (``civicconnector.connectors.municode.hash_bytes`` /
``detect_changes``) to two more granular levels, across all three
connectors' canonical schema:

* **Meeting-level** (``hash_meeting`` / ``detect_meeting_changes``): compares
  a meeting's own fields (agenda/minutes/video URLs, status) across polls.
  Works for every connector, including CivicClerk and Municode, whose
  ``get_items()`` return no item-level data (see IMPLEMENTATION_PLAN.md
  Phases 3-4) — a changed ``content_hash`` on the meeting itself is the only
  agenda-revision signal those two platforms can offer at present.
* **Item-level** (``hash_item`` / ``detect_agenda_changes``): compares a
  meeting's ``AgendaItem`` list across polls, for connectors (currently
  Legistar) that populate items. Flags items added, amended, or pulled
  since the last posting — the differentiated signal called out in idea #32
  as not surfaced natively by any vendor platform.

Per the existing ``detect_changes()`` contract in ``connectors/municode.py``,
both functions here are stateless: the caller supplies the previous poll's
hashes (however it persists them — this toolkit has no storage layer of its
own) and receives back the current hashes to persist for the next poll.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional

from civicconnector.models import AgendaItem, Meeting

# Fields that define an agenda item's substance for diff purposes.
# ``action_source``/``confidence`` are provenance metadata, not content, so a
# connector backfilling them (e.g. once minutes are processed) must not
# register as an "amended" item on its own.
_ITEM_DIFF_FIELDS = ("seq", "number", "title", "matter_id", "action_name", "passed", "roll_call")

# Fields that define a meeting's substance for diff purposes. ``status`` is
# included because e.g. Legistar's ``EventAgendaStatusName`` flips from
# "Draft" to "Final" as an agenda is posted/amended. ``content_hash`` is
# included so a connector that hashes the fetched document bytes (e.g.
# Municode's ``hash_bytes``) surfaces a same-URL content revision as
# "changed" here too -- without it, a reposted agenda whose bytes change at
# a stable URL is misclassified as "unchanged" (idea #32, PR #7 review).
_MEETING_DIFF_FIELDS = ("agenda_url", "minutes_url", "video_url", "status", "content_hash")


def _hash_fields(obj: object, fields: tuple) -> str:
    parts = "\x1f".join(str(getattr(obj, field)) for field in fields)
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def hash_item(item: AgendaItem) -> str:
    """Content hash of the fields that define an agenda item's substance."""
    return _hash_fields(item, _ITEM_DIFF_FIELDS)


def hash_meeting(meeting: Meeting) -> str:
    """Content hash of the fields that define a meeting's agenda-revision
    substance (independent of the ``content_hash`` field on ``Meeting``
    itself, which a connector may or may not populate)."""
    return _hash_fields(meeting, _MEETING_DIFF_FIELDS)


@dataclass
class AgendaItemChange:
    """Result of comparing one AgendaItem's current content hash to the last
    known hash for its ``native_id`` within a meeting. ``status`` is
    ``"added"`` (no prior hash), ``"amended"`` (hash differs), ``"unchanged"``
    (hash matches), or ``"pulled"`` (native_id was present in a prior poll
    but is absent from the current item list -- pulled since last posting).
    """

    meeting_id: str
    native_id: str
    status: str
    content_hash: Optional[str]  # None for "pulled"


@dataclass
class MeetingChange:
    """Result of comparing one Meeting's current content hash to the last
    known hash for its ``native_id``. ``status`` is ``"new"`` (no prior
    hash), ``"changed"`` (hash differs), or ``"unchanged"``."""

    native_id: str
    status: str
    content_hash: str


def detect_agenda_changes(
    meeting_id: str,
    items: List[AgendaItem],
    previous_hashes: Dict[str, str],
) -> List[AgendaItemChange]:
    """Compare ``items`` (the current poll's agenda items for one meeting)
    to ``previous_hashes`` (a ``{native_id: content_hash}`` map from the last
    poll for that same meeting, supplied by the caller). Returns one
    ``AgendaItemChange`` per ``native_id`` seen in either the current items
    or the previous hashes: ``"added"``/``"amended"``/``"unchanged"`` for
    items present now, and ``"pulled"`` for native_ids present previously
    but absent now.
    """
    changes: List[AgendaItemChange] = []
    seen_native_ids = set()
    for item in items:
        seen_native_ids.add(item.native_id)
        current_hash = hash_item(item)
        prior_hash = previous_hashes.get(item.native_id)
        if prior_hash is None:
            status = "added"
        elif prior_hash != current_hash:
            status = "amended"
        else:
            status = "unchanged"
        changes.append(
            AgendaItemChange(
                meeting_id=meeting_id,
                native_id=item.native_id,
                status=status,
                content_hash=current_hash,
            )
        )

    for native_id in previous_hashes:
        if native_id not in seen_native_ids:
            changes.append(
                AgendaItemChange(
                    meeting_id=meeting_id,
                    native_id=native_id,
                    status="pulled",
                    content_hash=None,
                )
            )

    return changes


def detect_meeting_changes(
    meetings: List[Meeting],
    previous_hashes: Dict[str, str],
) -> List[MeetingChange]:
    """Compare ``meetings`` (the current poll's meetings for one
    jurisdiction) to ``previous_hashes`` (a ``{native_id: content_hash}`` map
    from the last poll, supplied by the caller). Meetings that disappear
    between polls (cancelled/removed) are not reported here -- callers that
    need that signal should diff the native_id sets of successive
    ``list_meetings()`` calls directly; this function only classifies
    meetings present in the current poll.
    """
    changes: List[MeetingChange] = []
    for meeting in meetings:
        current_hash = hash_meeting(meeting)
        prior_hash = previous_hashes.get(meeting.native_id)
        if prior_hash is None:
            status = "new"
        elif prior_hash != current_hash:
            status = "changed"
        else:
            status = "unchanged"
        changes.append(
            MeetingChange(native_id=meeting.native_id, status=status, content_hash=current_hash)
        )
    return changes


def hashes_from_items(items: List[AgendaItem]) -> Dict[str, str]:
    """Build the ``{native_id: content_hash}`` map a caller should persist
    after this poll, to pass as ``previous_hashes`` on the next call to
    ``detect_agenda_changes()`` for the same meeting."""
    return {item.native_id: hash_item(item) for item in items}


def hashes_from_meetings(meetings: List[Meeting]) -> Dict[str, str]:
    """Build the ``{native_id: content_hash}`` map a caller should persist
    after this poll, to pass as ``previous_hashes`` on the next call to
    ``detect_meeting_changes()`` for the same jurisdiction."""
    return {meeting.native_id: hash_meeting(meeting) for meeting in meetings}
