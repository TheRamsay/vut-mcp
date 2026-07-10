import hashlib
import re
from datetime import datetime

from selectolax.parser import HTMLParser, Node

from vut_studis.models import CourseUpdate, CourseUpdates
from vut_studis.parsers.common import clean_text, same_origin_url

_REQUIRED_HEADERS = {"date", "title", "course", "author"}
_HEADER_NAMES = {
    "datum": "date",
    "aktualita": "title",
    "předmět": "course",
    "vystavil": "author",
}
_COURSE = re.compile(r"^([A-Za-z0-9-]+)\s*[-–—]\s*(.+)$")
_PUBLISHED_AT = re.compile(
    r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


def parse_course_updates_html(html: str, base_url: str) -> CourseUpdates:
    """Parse bounded course-update metadata without following any announcement links."""
    tree = HTMLParser(html)
    updates_by_id: dict[str, CourseUpdate] = {}

    for table in tree.css("table"):
        headers = _header_indices(table)
        if headers is None:
            continue

        for row in table.css("tr"):
            update = _parse_row(row, headers=headers, base_url=base_url)
            if update is not None:
                updates_by_id.setdefault(update.id, update)

    return CourseUpdates(
        items=sorted(
            updates_by_id.values(),
            key=lambda update: (update.published_at, update.id),
            reverse=True,
        )
    )


def _header_indices(table: Node) -> dict[str, int] | None:
    for row in table.css("tr"):
        cells = row.css("th")
        if not cells:
            continue

        headers = {
            _HEADER_NAMES.get(_normalise_header(clean_text(cell))): index
            for index, cell in enumerate(cells)
            if _HEADER_NAMES.get(_normalise_header(clean_text(cell))) is not None
        }
        if _REQUIRED_HEADERS.issubset(headers):
            return headers

    return None


def _parse_row(
    row: Node,
    *,
    headers: dict[str, int],
    base_url: str,
) -> CourseUpdate | None:
    cells = row.css("td")
    if len(cells) <= max(headers.values()):
        return None

    published_at = _parse_published_at(clean_text(cells[headers["date"]]))
    title = clean_text(cells[headers["title"]])
    course = _parse_course(clean_text(cells[headers["course"]]))
    author = clean_text(cells[headers["author"]])
    if published_at is None or not title or course is None or not author:
        return None

    course_code, course_name = course
    url = _first_same_origin_link(cells[headers["title"]], base_url)
    course_url = _first_same_origin_link(cells[headers["course"]], base_url)
    identifier = _update_id(
        published_at=published_at,
        title=title,
        course_code=course_code,
        url=url,
    )
    return CourseUpdate(
        id=identifier,
        published_at=published_at,
        title=title,
        course_code=course_code,
        course_name=course_name,
        author=author,
        url=url,
        course_url=course_url,
    )


def _normalise_header(text: str) -> str:
    return text.removesuffix(":").casefold()


def _parse_published_at(text: str) -> datetime | None:
    match = _PUBLISHED_AT.fullmatch(text)
    if match is None:
        return None

    day, month, year, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
        )
    except ValueError:
        return None


def _parse_course(text: str) -> tuple[str, str] | None:
    match = _COURSE.fullmatch(text)
    if match is None:
        return None

    course_code, course_name = match.groups()
    return course_code, course_name.strip()


def _first_same_origin_link(node: Node, base_url: str) -> str | None:
    for link in node.css("a"):
        href = link.attributes.get("href")
        if href is None:
            continue
        if url := same_origin_url(href, base_url):
            return url
    return None


def _update_id(*, published_at: datetime, title: str, course_code: str, url: str | None) -> str:
    value = "\x1f".join((published_at.isoformat(), title, course_code, url or ""))
    return hashlib.sha256(value.encode()).hexdigest()[:16]
