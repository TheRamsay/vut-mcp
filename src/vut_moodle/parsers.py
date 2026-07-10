"""Narrow HTML parsers for Moodle's authenticated web pages."""

from datetime import UTC, datetime
from urllib.parse import ParseResult, parse_qs, urljoin, urlparse

from selectolax.parser import HTMLParser, Node

from vut_moodle.errors import MoodleDataError
from vut_moodle.models import (
    MoodleAssignment,
    MoodleCourse,
    MoodleCourseResource,
    MoodleFile,
)

_RESOURCE_TYPES_BY_PATH = {
    "/mod/resource/view.php": "file",
    "/mod/folder/view.php": "folder",
    "/mod/page/view.php": "page",
    "/mod/url/view.php": "url",
}


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


def parse_course_resources(
    html: str,
    *,
    base_url: str,
    course: MoodleCourse,
) -> list[MoodleCourseResource]:
    """Extract same-origin Moodle activity metadata from one course outline.

    The course page is only inspected; linked activities and plugin files are
    deliberately not fetched here.
    """
    tree = HTMLParser(html)
    resources: list[MoodleCourseResource] = []
    seen_ids: set[int] = set()

    for node in tree.css("a"):
        url = _moodle_url(node.attributes.get("href"), base_url=base_url)
        if url is None:
            continue

        parsed = urlparse(url)
        activity_id = parse_positive_query_id_for_module(parsed)
        if activity_id is None or activity_id in seen_ids:
            continue

        name = _link_name(node)
        if not name:
            continue

        activity = _nearest_activity(node)
        resources.append(
            MoodleCourseResource(
                course_id=course.id,
                activity_id=activity_id,
                section_name=_nearest_section_name(node),
                name=name,
                resource_type=_RESOURCE_TYPES_BY_PATH.get(parsed.path, "unknown"),
                url=url,
                files=(
                    parse_pluginfile_links(activity, base_url=base_url)
                    if activity is not None
                    else []
                ),
            )
        )
        seen_ids.add(activity_id)

    return resources


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


def parse_positive_query_id_for_module(parsed: ParseResult) -> int | None:
    """Return a positive activity ID only for a Moodle module view link."""
    path_parts = parsed.path.removeprefix("/mod/").split("/")
    if (
        not parsed.path.startswith("/mod/")
        or len(path_parts) != 2
        or not path_parts[0]
        or path_parts[1] != "view.php"
    ):
        return None

    value = parse_qs(parsed.query).get("id", [""])[0]
    return int(value) if value.isdecimal() and int(value) > 0 else None


def parse_pluginfile_links(tree: HTMLParser | Node, *, base_url: str) -> list[MoodleFile]:
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


def parse_resource_files(html: str, *, base_url: str) -> list[MoodleFile]:
    """Extract same-origin plugin-file metadata from one Moodle activity page."""
    return parse_pluginfile_links(HTMLParser(html), base_url=base_url)


def parse_url_target(html: str, *, base_url: str) -> str | None:
    """Return a URL activity's direct HTTP(S) destination without requesting it."""
    tree = HTMLParser(html)
    main = tree.css_first("#region-main, [role='main'], main")
    if main is None:
        return None
    for node in main.css("a"):
        href = node.attributes.get("href")
        if not href:
            continue
        target = urljoin(base_url, href)
        parsed = urlparse(target)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            continue
        if _origin(target) != _origin(base_url):
            return target
    return None


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

    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        port or {"http": 80, "https": 443}.get(parsed.scheme.lower()),
    )


def _link_name(node: Node) -> str:
    """Use a visible label, with accessible labels as a safe fallback."""
    text = node.text(separator=" ", strip=True).strip()
    for hidden_label in reversed(
        [hidden.text(separator=" ", strip=True).strip() for hidden in node.css(".accesshide")]
    ):
        if hidden_label and text.endswith(f" {hidden_label}"):
            text = text.removesuffix(f" {hidden_label}").rstrip()
    if text:
        return text
    attributes = node.attributes
    return attributes.get("aria-label") or attributes.get("title") or ""


def _nearest_activity(node: Node) -> Node | None:
    """Find the enclosing Moodle activity container, if Moodle supplied one."""
    current: Node | None = node
    while current is not None:
        attributes = current.attributes
        classes = set(attributes.get("class", "").split())
        if "activity" in classes or attributes.get("id", "").startswith("module-"):
            return current
        current = current.parent
    return None


def _nearest_section_name(node: Node) -> str | None:
    """Return the closest enclosing course-section heading, when present."""
    current: Node | None = node
    while current is not None:
        attributes = current.attributes
        classes = set(attributes.get("class", "").split())
        identifier = attributes.get("id", "")
        if "section" in classes or "course-section" in classes or identifier.startswith("section-"):
            heading = current.css_first(
                ".sectionname, [data-region='sectionname'], h1, h2, h3, h4, h5, h6"
            )
            if heading is not None and (name := heading.text(strip=True)):
                return name
        current = current.parent
    return None
