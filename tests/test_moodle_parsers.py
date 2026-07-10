from datetime import UTC, datetime

import pytest

from vut_moodle.errors import MoodleDataError
from vut_moodle.models import MoodleCourse
from vut_moodle.parsers import (
    parse_assignment_page,
    parse_course_assignments,
    parse_dashboard_courses,
)

ANONYMIZED_ASSIGNMENT_HTML = """
<!doctype html>
<html>
  <body>
    <h1>Project 1</h1>
    <section class="submissionstatustable">
      <time data-timestamp="1784066340">Tuesday, 14 July 2026, 9:59 PM</time>
    </section>
    <a href="/pluginfile.php/17/mod_assign/introattachment/0/specification.pdf">
      specification.pdf
    </a>
  </body>
</html>
"""


def test_parse_dashboard_courses_uses_course_view_ids() -> None:
    courses = parse_dashboard_courses(
        '<a href="/course/view.php?id=42">Algorithms</a>',
        base_url="https://moodle.vut.cz/my/",
    )

    assert courses == [
        MoodleCourse(
            id=42,
            name="Algorithms",
            url="https://moodle.vut.cz/course/view.php?id=42",
        )
    ]


def test_parse_course_assignments_uses_assignment_view_ids() -> None:
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )

    assignments = parse_course_assignments(
        '<a href="/mod/assign/view.php?id=17">Project 1</a>',
        base_url=course.url,
        course=course,
    )

    assert assignments == [(17, "https://moodle.vut.cz/mod/assign/view.php?id=17")]


def test_parse_assignment_page_extracts_deadline_and_attachment_metadata() -> None:
    assignment = parse_assignment_page(
        ANONYMIZED_ASSIGNMENT_HTML,
        base_url="https://moodle.vut.cz/mod/assign/view.php?id=17",
        course_id=42,
    )

    assert assignment.name == "Project 1"
    assert assignment.due_at == datetime(2026, 7, 14, 21, 59, tzinfo=UTC)
    assert assignment.files[0].name == "specification.pdf"
    assert assignment.files[0].url == (
        "https://moodle.vut.cz/pluginfile.php/17/mod_assign/introattachment/0/specification.pdf"
    )


def test_parsers_ignore_links_outside_configured_moodle_origin() -> None:
    courses = parse_dashboard_courses(
        """
        <a href="https://evil.example/course/view.php?id=13">Not a course</a>
        <a href="https://moodle.vut.cz:invalid/course/view.php?id=14">Invalid course</a>
        <a href="https://moodle.vut.cz/course/view.php?id=42">Algorithms</a>
        """,
        base_url="https://moodle.vut.cz/my/",
    )
    assignment = parse_assignment_page(
        """
        <h1>Project 1</h1>
        <a href="https://evil.example/pluginfile.php/17/mod_assign/introattachment/0/bad.pdf">
          bad.pdf
        </a>
        """,
        base_url="https://moodle.vut.cz/mod/assign/view.php?id=17",
        course_id=42,
    )

    assert [course.id for course in courses] == [42]
    assert assignment.files == []


def test_parse_assignment_page_requires_an_assignment_id_and_heading() -> None:
    with pytest.raises(MoodleDataError, match="id query parameter"):
        parse_assignment_page(
            "<h1>Project 1</h1>",
            base_url="https://moodle.vut.cz/mod/assign/view.php",
            course_id=42,
        )

    with pytest.raises(MoodleDataError, match="no heading"):
        parse_assignment_page(
            "<p>No heading</p>",
            base_url="https://moodle.vut.cz/mod/assign/view.php?id=17",
            course_id=42,
        )
