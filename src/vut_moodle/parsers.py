"""Narrow HTML parsers for Moodle's authenticated web pages."""

from datetime import UTC, datetime
from urllib.parse import ParseResult, parse_qs, urljoin, urlparse

from selectolax.parser import HTMLParser

from vut_moodle.errors import MoodleDataError
from vut_moodle.models import MoodleAssignment, MoodleCourse, MoodleFile


def parse_dashboard_courses(html: str, *, base_url: str) -> list[MoodleCourse]:
    """Extract uniquely identified course links from Moodle's dashboard."""
    courses: list[MoodleCourse] = []
    seen_ids: set[int] = set()

    for node in HTMLParser(html).css("a"):
        url = _moodle_url(node.attributes.get("href"), base_url=base_url)
        if url is None:
            continue

        course_id = parse_positive_query_id(urlparse(url), path="/course/view.php")
        if course_id is None or course_id in seen_ids:
            continue

        name = node.text(strip=True)
        if not name:
            continue

        courses.append(MoodleCourse(id=course_id, name=name, url=url))
        seen_ids.add(course_id)

    return courses


def parse_course_assignments(
    html: str,
    *,
    base_url: str,
    course: MoodleCourse,
) -> list[tuple[int, str]]:
    """Extract assignment activity IDs and Moodle URLs from a course page."""
    del course  # The caller owns course metadata; this parser only identifies activities.
    assignments: list[tuple[int, str]] = []
    seen_ids: set[int] = set()

    for node in HTMLParser(html).css("a"):
        url = _moodle_url(node.attributes.get("href"), base_url=base_url)
        if url is None:
            continue

        assignment_id = parse_positive_query_id(urlparse(url), path="/mod/assign/view.php")
        name = node.text(strip=True)
        if assignment_id is None or not name or assignment_id in seen_ids:
            continue

        assignments.append((assignment_id, url))
        seen_ids.add(assignment_id)

    return assignments


def parse_assignment_page(
    html: str,
    *,
    base_url: str,
    course_id: int,
    course_name: str | None = None,
) -> MoodleAssignment:
    """Parse one assignment's heading, due time, and linked-file metadata."""
    tree = HTMLParser(html)
    assignment_id = parse_positive_query_id(urlparse(base_url), path="/mod/assign/view.php")
    if assignment_id is None:
        raise MoodleDataError("Moodle assignment URL is missing its id query parameter.")

    heading = tree.css_first("h1")
    if heading is None or not (name := heading.text(strip=True)):
        raise MoodleDataError("Moodle assignment page has no heading.")

    return MoodleAssignment(
        id=assignment_id,
        course_id=course_id,
        course_name=course_name,
        name=name,
        url=base_url,
        due_at=parse_moodle_due_date(tree),
        files=parse_pluginfile_links(tree, base_url=base_url),
    )


def parse_positive_query_id(parsed: ParseResult, *, path: str) -> int | None:
    """Return a positive decimal ``id`` query value only for the expected path."""
    if parsed.path != path:
        return None

    value = parse_qs(parsed.query).get("id", [""])[0]
    return int(value) if value.isdecimal() and int(value) > 0 else None


def parse_pluginfile_links(tree: HTMLParser, *, base_url: str) -> list[MoodleFile]:
    """Return same-origin plugin-file links without requesting file bytes."""
    files: list[MoodleFile] = []
    seen_urls: set[str] = set()

    for node in tree.css("a"):
        url = _moodle_url(node.attributes.get("href"), base_url=base_url)
        name = node.text(strip=True)
        if url is None or not urlparse(url).path.startswith("/pluginfile.php/") or not name:
            continue
        if url in seen_urls:
            continue

        files.append(MoodleFile(name=name, url=url))
        seen_urls.add(url)

    return files


def parse_moodle_due_date(tree: HTMLParser) -> datetime | None:
    """Extract the first Moodle timestamp-bearing time element as UTC."""
    node = tree.css_first("time[data-timestamp]")
    if node is None:
        return None

    value = node.attributes.get("data-timestamp", "")
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _moodle_url(href: str | None, *, base_url: str) -> str | None:
    """Resolve a link only when its exact origin matches the configured Moodle page."""
    if not href:
        return None

    url = urljoin(base_url, href)
    base_origin = _origin(base_url)
    if base_origin is None or _origin(url) != base_origin:
        return None
    return url


def _origin(url: str) -> tuple[str, str, int | None] | None:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None

    return (parsed.scheme.lower(), (parsed.hostname or "").lower(), port)
