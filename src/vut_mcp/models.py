"""Neutral, read-only models for the cross-source agenda."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from vut_studis import PendingActionSeverity


class AgendaModel(BaseModel):
    """Immutable base model for agenda responses."""

    model_config = ConfigDict(frozen=True)


class AgendaSource(StrEnum):
    STUDIS = "studis"
    MOODLE = "moodle"


class AgendaItem(AgendaModel):
    """One actionable or informational item from StudIS or Moodle."""

    id: str
    source: AgendaSource
    title: str
    course_name: str | None = None
    due_at: datetime | None = None
    starts_at: datetime | None = None
    severity: PendingActionSeverity | None = None
    status: str | None = None
    url: str | None = None
    detail: str | None = None


class Agenda(AgendaModel):
    """A bounded, read-only timeline composed from StudIS and Moodle metadata."""

    generated_at: datetime
    horizon_days: int
    items: list[AgendaItem] = Field(default_factory=list)
    studis_count: int
    moodle_count: int
    truncated_count: int
