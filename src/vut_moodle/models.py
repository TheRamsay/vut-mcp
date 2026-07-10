"""Immutable, JSON-serializable Moodle domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MoodleModel(BaseModel):
    """Base model for Moodle data returned by the read-only integration."""

    model_config = ConfigDict(frozen=True)


class MoodleFile(MoodleModel):
    name: str
    url: str
    size_bytes: int | None = None
    mimetype: str | None = None
    modified_at: datetime | None = None


class MoodleCourse(MoodleModel):
    id: int
    name: str
    short_name: str | None = None
    url: str


class MoodleAssignment(MoodleModel):
    id: int
    course_id: int
    course_name: str | None = None
    name: str
    url: str
    due_at: datetime | None = None
    cutoff_at: datetime | None = None
    submission_status: Literal["new", "draft", "submitted", "unknown"] = "unknown"
    files: list[MoodleFile] = Field(default_factory=list)
