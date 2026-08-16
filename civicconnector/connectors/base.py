"""Connector interface (Phase 1).

Every platform-specific connector implements exactly these four methods.
Anything a platform can't do returns ``None`` (or an empty list), never a
guess — per IMPLEMENTATION_PLAN.md's extraction rule.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from civicconnector.models import AgendaItem, Body, Document, Meeting


class Connector(ABC):
    """Abstract base for a platform connector (Legistar, CivicClerk, Municode, ...)."""

    @abstractmethod
    def list_bodies(self) -> List[Body]:
        """Return all governing bodies known to this jurisdiction."""

    @abstractmethod
    def list_meetings(self, since: Optional[datetime] = None) -> List[Meeting]:
        """Return meetings, optionally filtered to those changed since ``since``."""

    @abstractmethod
    def get_items(self, meeting: Meeting) -> List[AgendaItem]:
        """Return agenda items for a given meeting."""

    @abstractmethod
    def get_documents(self, meeting: Meeting) -> List[Document]:
        """Return documents (agenda, minutes, packet, ...) for a given meeting."""
