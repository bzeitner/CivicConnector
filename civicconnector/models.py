"""Canonical schema (Phase 1).

One record shape shared by all connectors, per IMPLEMENTATION_PLAN.md and
IdeaFlow idea #32 / research entry #80. Fields intentionally allow ``None`` —
a connector must report what it does not know rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ActionSource(str, Enum):
    """Where an AgendaItem's decision/action data came from.

    Research entry #80 measured that Legistar's structured "action" field is
    populated on only ~0-40% of items and lags until minutes are processed,
    so every item must carry an explicit provenance flag rather than implying
    uniform coverage.
    """

    API = "api"
    MINUTES_PDF = "minutes_pdf"
    NONE = "none"


@dataclass
class Jurisdiction:
    id: str
    name: str
    platform: str  # e.g. "legistar", "civicclerk", "municode"
    base_url: str
    tz: str
    poll_policy: Optional[str] = None


@dataclass
class Body:
    jurisdiction_id: str
    native_id: str
    name: str
    type: Optional[str] = None


@dataclass
class Meeting:
    body_id: str
    native_id: str
    starts_at: datetime
    status: Optional[str] = None
    agenda_url: Optional[str] = None
    minutes_url: Optional[str] = None
    video_url: Optional[str] = None
    first_seen_at: Optional[datetime] = None
    last_changed_at: Optional[datetime] = None
    content_hash: Optional[str] = None


@dataclass
class AgendaItem:
    meeting_id: str
    native_id: str
    seq: Optional[int] = None
    number: Optional[str] = None
    title: Optional[str] = None
    matter_id: Optional[str] = None
    action_name: Optional[str] = None
    passed: Optional[bool] = None
    roll_call: Optional[bool] = None
    action_source: ActionSource = ActionSource.NONE
    confidence: Optional[float] = None


@dataclass
class Vote:
    agenda_item_id: str
    person: str
    vote_value: str
    source: Optional[str] = None


@dataclass
class Document:
    meeting_id: str
    kind: str
    url: str
    retrieved_at: Optional[datetime] = None
    sha256: Optional[str] = None
    text_source: Optional[str] = None
