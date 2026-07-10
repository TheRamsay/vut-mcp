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


class MoodleFileContent(MoodleModel):
    file: MoodleFile
    content_type: str
    text: str
    text_truncated: bool
    bytes_downloaded: int
    extractor: Literal["pdf", "text"]


class MoodleCourse(MoodleModel):
    id: int
    name: str
    short_name: str | None = None
    url: str


class MoodleCourseResource(MoodleModel):
    """A read-only Moodle activity and its listed attached-file metadata."""

    course_id: int
    activity_id: int
    section_name: str | None = None
    name: str
    resource_type: Literal["file", "folder", "page", "url", "unknown"]
    url: str
    target_url: str | None = None
    files: list[MoodleFile] = Field(default_factory=list)


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
