"""Read-only Moodle integration for VUT."""

from vut_moodle.client import MoodleClient
from vut_moodle.models import MoodleAssignment, MoodleCourse, MoodleFile

__all__ = ["MoodleAssignment", "MoodleClient", "MoodleCourse", "MoodleFile"]
