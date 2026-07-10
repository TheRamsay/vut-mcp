from datetime import UTC, datetime
from pathlib import Path

import pytest

from vut_moodle.errors import MoodleDataError
from vut_moodle.models import MoodleCourse
from vut_moodle.parsers import (
    parse_assignment_page,
    parse_course_assignments,
    parse_course_resources,
    parse_dashboard_courses,
    parse_resource_files,
    parse_url_target,
)

FIXTURES = Path(__file__).parent / "fixtures"

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


def test_parse_course_resources_extracts_supported_types_and_section_context() -> None:
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )

    resources = parse_course_resources(
        (FIXTURES / "moodle_course_resources.html").read_text(),
        base_url=course.url,
        course=course,
    )

    assert [(resource.activity_id, resource.resource_type) for resource in resources] == [
        (101, "file"),
        (102, "folder"),
        (103, "page"),
        (104, "url"),
        (105, "unknown"),
        (201, "file"),
    ]
    assert resources[0].course_id == 42
    assert resources[0].section_name == "Week 1: Foundations"
    assert resources[0].files[0].name == "outline.pdf"
    assert resources[0].files[0].url == (
        "https://moodle.vut.cz/pluginfile.php/7/mod_resource/content/1/outline.pdf"
    )
    assert len(resources[0].files) == 1
    assert resources[-1].section_name == "Week 2: Practice"
    assert resources[-1].name == "Exercises"


def test_parse_resource_files_returns_only_same_origin_pluginfile_links() -> None:
    files = parse_resource_files(
        """
        <a href="/pluginfile.php/7/mod_folder/content/0/example.pdf">example.pdf</a>
        <a href="/pluginfile.php/7/mod_folder/content/0/example.pdf">duplicate.pdf</a>
        <a href="https://outside.example/pluginfile.php/7/mod_folder/content/0/bad.pdf">bad.pdf</a>
        <a href="/mod/resource/view.php?id=101">Not a file</a>
        """,
        base_url="https://moodle.vut.cz/mod/folder/view.php?id=102",
    )

    assert [(file.name, file.url) for file in files] == [
        (
            "example.pdf",
            "https://moodle.vut.cz/pluginfile.php/7/mod_folder/content/0/example.pdf",
        )
    ]


def test_parse_course_resources_excludes_hidden_activity_type_from_name() -> None:
    course = MoodleCourse(
        id=42,
        name="Algorithms",
        url="https://moodle.vut.cz/course/view.php?id=42",
    )

    resources = parse_course_resources(
        """
        <div class="activity">
          <a href="/mod/url/view.php?id=104">
            Lecture 1 <span class="accesshide">URL</span>
          </a>
        </div>
        """,
        base_url=course.url,
        course=course,
    )

    assert resources[0].name == "Lecture 1"


def test_parse_url_target_returns_only_the_main_external_destination() -> None:
    target = parse_url_target(
        """
        <header><a href="https://www.vut.cz">Site navigation</a></header>
        <main>
          <a href="https://slides.example/lecture-7">Open presentation</a>
        </main>
        """,
        base_url="https://moodle.vut.cz/mod/url/view.php?id=104",
    )

    assert target == "https://slides.example/lecture-7"


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
