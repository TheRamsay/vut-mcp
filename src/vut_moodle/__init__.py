"""Read-only Moodle integration for VUT."""

from vut_moodle.client import MoodleClient
from vut_moodle.extraction import extract_file_content
from vut_moodle.models import (
    MoodleAssignment,
    MoodleCourse,
    MoodleCourseResource,
    MoodleFile,
    MoodleFileContent,
)

__all__ = [
    "MoodleAssignment",
    "MoodleClient",
    "MoodleCourse",
    "MoodleCourseResource",
    "MoodleFile",
    "MoodleFileContent",
    "extract_file_content",
]
