from __future__ import annotations

import re
from datetime import date, datetime, time
from urllib.parse import parse_qs, urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

from vut_studis.models import ScheduleItem
from vut_studis.parsers.common import clean_text

_VUT_HOSTS = {"vut.cz", "www.vut.cz"}
_DATE_PATTERN = re.compile(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(20\d{2})")
_TIME_PATTERN = re.compile(
    r"\b(\d{1,2}):(\d{2})\s*(?:-|–|—|až)\s*(\d{1,2}):(\d{2})\b",
    re.IGNORECASE,
)
_COURSE_PATTERN = re.compile(r"^([A-Z][A-Z0-9-]{1,})\s*(?:[-–—:]\s*)?(.*)$")
type DefaultYear = int | tuple[int, int]


def parse_schedule_html(html: str, *, base_url: str = "") -> list[ScheduleItem]:
    """Parse read-only entries rendered in the StudIS personal timetable."""
    tree = HTMLParser(html)
    default_year = _parse_default_year(tree)
    items: list[ScheduleItem] = []
    current_date: date | None = None

    nodes = tree.css("body *") if tree.body is not None else tree.css("*")
    for node in nodes:
        if node.tag not in {"h1", "h2", "h3", "h4", "h5", "h6", "table"}:
            continue
        if node.tag != "table":
            current_date = _parse_date(clean_text(node), default_year) or current_date
            continue

        table_date = _date_from_node_or_ancestor(node, default_year)
        items.extend(
            _parse_table(
                node,
                day=table_date or current_date,
                default_year=default_year,
                base_url=base_url,
            )
        )

    return _deduplicate(items)


def _parse_table(
    table: Node,
    *,
    day: date | None,
    default_year: DefaultYear | None,
    base_url: str,
) -> list[ScheduleItem]:
    headers = _header_indexes(table)
    items: list[ScheduleItem] = []
    current_day = day

    for row in table.css("tr"):
        cells = row.css("td")
        if not cells:
            continue

        cell_texts = [clean_text(cell) for cell in cells]
        rendered_text = " ".join(cell_texts)
        row_date = _parse_date(rendered_text, default_year)
        if row_date is not None:
            current_day = row_date
        time_cell = _cell_at(cells, headers.get("time"))
        time_text = clean_text(time_cell) if time_cell is not None else rendered_text
        time_range = _parse_time_range(time_text)
        if time_range is None:
            continue
        if current_day is None:
            continue

        course_cell = _cell_at(cells, headers.get("course"))
        course_code, course_name = _parse_course(course_cell)
        if not course_name:
            continue

        starts_at = datetime.combine(current_day, time_range[0])
        ends_at = datetime.combine(current_day, time_range[1])
        if ends_at <= starts_at:
            continue

        items.append(
            ScheduleItem(
                course_code=course_code,
                course_name=course_name,
                starts_at=starts_at,
                ends_at=ends_at,
                room=_text_or_none(_cell_at(cells, headers.get("room"))),
                teacher=_text_or_none(_cell_at(cells, headers.get("teacher"))),
                kind=_text_or_none(_cell_at(cells, headers.get("kind"))),
                detail_url=_safe_detail_url(course_cell, base_url),
            )
        )

    return items


def _header_indexes(table: Node) -> dict[str, int]:
    aliases = {
        "time": {"čas", "cas", "čas od-do", "čas od do"},
        "course": {"předmět", "predmet", "kurz"},
        "kind": {"typ", "druh", "forma", "akce"},
        "room": {"místnost", "mistnost", "učebna", "ucebna"},
        "teacher": {"vyučující", "vyucujici", "učitel", "ucitel", "cvičící", "cvicici"},
    }
    for row in table.css("tr"):
        headers = row.css("th")
        if not headers:
            continue
        result: dict[str, int] = {}
        for index, header in enumerate(headers):
            label = clean_text(header).rstrip(":").casefold()
            for key, accepted in aliases.items():
                if label in accepted:
                    result[key] = index
        if "time" in result and "course" in result:
            return result
    return {}


def _parse_default_year(tree: HTMLParser) -> DefaultYear | None:
    text = clean_text(tree.body) if tree.body is not None else ""
    years = re.search(r"(?<!\d)(20\d{2})\s*/\s*(20\d{2})(?!\d)", text)
    if years:
        return int(years.group(1)), int(years.group(2))
    match = re.search(r"\b(20\d{2})\b", text)
    return int(match.group(1)) if match else None


def _date_from_node_or_ancestor(node: Node, default_year: DefaultYear | None) -> date | None:
    current: Node | None = node
    while current is not None:
        for name in ("data-date", "data-day"):
            if value := current.attributes.get(name):
                parsed = _parse_date(value, default_year)
                if parsed:
                    return parsed
        current = current.parent
    return None


def _parse_date(text: str, default_year: DefaultYear | None) -> date | None:
    match = _DATE_PATTERN.search(text)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    if default_year is None:
        return None
    match = re.search(r"\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\b", text)
    if not match:
        return None
    day, month = map(int, match.groups())
    if isinstance(default_year, tuple):
        year = default_year[0] if month >= 8 else default_year[1]
    else:
        year = default_year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_time_range(text: str) -> tuple[time, time] | None:
    match = _TIME_PATTERN.search(text)
    if not match:
        return None
    start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
    try:
        return time(start_hour, start_minute), time(end_hour, end_minute)
    except ValueError:
        return None


def _parse_course(cell: Node | None) -> tuple[str | None, str]:
    if cell is None:
        return None, ""
    text = clean_text(cell)
    code = None
    if link := cell.css_first("a"):
        linked_text = clean_text(link)
        if re.fullmatch(r"[A-Z][A-Z0-9-]{1,}", linked_text):
            code = linked_text
            text = text.removeprefix(linked_text).lstrip(" -–—:\t")

    match = _COURSE_PATTERN.fullmatch(text)
    if match:
        code = code or match.group(1)
        text = match.group(2).strip()
    return code, text


def _safe_detail_url(cell: Node | None, base_url: str) -> str | None:
    if cell is None or not base_url:
        return None
    base = urlsplit(base_url)
    if base.scheme != "https" or base.hostname not in _VUT_HOSTS:
        return None

    for link in cell.css("a"):
        href = (link.attributes.get("href") or "").strip()
        if not href or href.casefold().startswith("javascript:"):
            continue
        resolved = urlsplit(urljoin(base_url, href))
        if (
            resolved.scheme != "https"
            or resolved.hostname not in _VUT_HOSTS
            or resolved.netloc != base.netloc
            or resolved.path != "/studis/student.phtml"
        ):
            continue
        query = parse_qs(resolved.query, keep_blank_values=True)
        if query.get("sn") == ["predmet_detail"] and set(query).issubset({"sn", "apid"}):
            return resolved.geturl()
    return None


def _cell_at(cells: list[Node], index: int | None) -> Node | None:
    if index is None or index >= len(cells):
        return None
    return cells[index]


def _text_or_none(cell: Node | None) -> str | None:
    return clean_text(cell) or None if cell is not None else None


def _deduplicate(items: list[ScheduleItem]) -> list[ScheduleItem]:
    seen: set[tuple[object, ...]] = set()
    unique: list[ScheduleItem] = []
    for item in items:
        key = (
            item.course_code,
            item.course_name,
            item.starts_at,
            item.ends_at,
            item.room,
            item.teacher,
            item.kind,
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
