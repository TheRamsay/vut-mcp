import re
from datetime import datetime
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from vut_studis.models import AssignmentSubmissionFile, CourseAssignment, CourseAssignments
from vut_studis.parsers.grades import parse_int

ASSIGNMENT_HEADERS = {
    "č.",
    "název",
    "vedoucí",
    "popis",
    "odevzdání",
    "registrován",
    "obs./max.",
    "informace",
}


def parse_course_assignments_html(html: str, base_url: str = "") -> CourseAssignments:
    tree = HTMLParser(html)
    course_code, course_name, academic_year = _parse_course_heading(tree)
    return CourseAssignments(
        course_code=course_code,
        course_name=course_name,
        academic_year=academic_year,
        assignments=_parse_assignments(tree, base_url=base_url),
    )


def parse_assignment_detail_html(html: str, base_url: str = "") -> dict[str, object]:
    tree = HTMLParser(html)
    text = _page_text(tree)
    submission_url = _find_link(tree, base_url, "sn=zadani_odevzdani")
    registered, registered_at = _parse_registered_detail(text)

    return {
        "description": _parse_between(text, "Popis:", "Registrace zadání"),
        "registration_opens_at": _parse_labeled_datetime(text, "Registrovat od:"),
        "registration_closes_at": _parse_labeled_datetime(text, "Registrovat do:"),
        "unregistration_closes_at": _parse_labeled_datetime(text, "Registraci lze zrušit do:"),
        "submit_until": _parse_labeled_datetime(text, "Zadání odevzdat do:"),
        "capacity_used": _parse_labeled_int(text, "Aktuálně přihlášených:"),
        "capacity_total": _parse_labeled_int(text, "Maximum studentů:"),
        "registered": registered,
        "registered_at": registered_at,
        "auto_registration": _parse_labeled_bool(text, "Přihlášení automaticky:"),
        "submission_url": submission_url,
    }


def parse_assignment_submission_html(
    html: str,
    base_url: str = "",
) -> list[AssignmentSubmissionFile]:
    tree = HTMLParser(html)
    files: list[AssignmentSubmissionFile] = []

    for table in tree.css("table"):
        headers = {_clean_text(header) for header in table.css("th")}
        if not {"Soubor", "Velikost", "Vloženo", "Vložil/a"}.issubset(headers):
            continue

        for row in table.css("tr"):
            cells = [_clean_text(cell) for cell in row.css("td")]
            if len(cells) != 4:
                continue

            files.append(
                AssignmentSubmissionFile(
                    name=cells[0],
                    size=cells[1] or None,
                    uploaded_at=_parse_datetime(cells[2]),
                    uploaded_by=cells[3] or None,
                    download_url=_find_link(row, base_url, "zadani_soubor.php"),
                )
            )

    return files


def _parse_assignments(tree: HTMLParser, *, base_url: str) -> list[CourseAssignment]:
    for table in tree.css("table"):
        headers = {_clean_text(header) for header in table.css("th")}
        if not ASSIGNMENT_HEADERS.issubset(headers):
            continue

        return _parse_assignments_table(table, base_url=base_url)

    return []


def _parse_assignments_table(table: Node, *, base_url: str) -> list[CourseAssignment]:
    assignments: list[CourseAssignment] = []
    assessment_order: int | None = None
    assessment_name: str | None = None
    assessment_category: str | None = None

    for row in table.css("tr"):
        headers = [_clean_text(header) for header in row.css("th")]
        cells = [_clean_text(cell) for cell in row.css("td")]

        if len(headers) == 1:
            assessment_order, assessment_name, assessment_category = _parse_numbered_name(
                headers[0]
            )
            continue

        if len(cells) != 8:
            continue

        used, total = _parse_capacity(cells[6])
        opens_at, closes_at = _parse_registration_window(cells[7])
        assignments.append(
            CourseAssignment(
                assessment_order=assessment_order,
                assessment_name=assessment_name,
                assessment_category=assessment_category,
                assignment_number=parse_int(cells[0].rstrip(".")),
                name=cells[1],
                teacher=cells[2] or None,
                description=cells[3] or None,
                submit_until=_parse_date_deadline(cells[4]),
                registered=_parse_registered(cells[5]),
                capacity_used=used,
                capacity_total=total,
                registration_info=cells[7] or None,
                registration_opens_at=opens_at,
                registration_closes_at=closes_at,
                can_register=_can_register(cells[7]),
                can_unregister=_can_unregister(cells[7]),
                detail_url=_find_link(row, base_url, "sn=zadani_detail"),
            )
        )

    return assignments


def _parse_course_heading(tree: HTMLParser) -> tuple[str, str | None, str | None]:
    for heading in tree.css("h3, h2"):
        text = _clean_text(heading)
        match = re.fullmatch(r"([A-Za-z0-9-]+)\s+-\s+(.+?)\(a\.r\.(\d{4}/\d{4})\)", text)
        if match:
            course_code, course_name, academic_year = match.groups()
            return course_code, course_name.strip(), academic_year

    return "", None, None


def _parse_numbered_name(text: str) -> tuple[int | None, str, str | None]:
    match = re.fullmatch(r"(\d+)\.\s+(.+?)(?:\s+\(([^()]*)\))?", text)
    if not match:
        return None, text, None

    order, name, category = match.groups()
    return int(order), name, category


def _parse_date_deadline(text: str) -> datetime | None:
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if not match:
        return None

    day, month, year = match.groups()
    return datetime(int(year), int(month), int(day), 23, 59, 59)


def _parse_datetime(text: str) -> datetime | None:
    match = re.fullmatch(
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        text,
    )
    if not match:
        return None

    day, month, year, hour, minute, second = match.groups()
    return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))


def _parse_labeled_datetime(text: str, label: str) -> datetime | None:
    value = _parse_labeled_value(text, label)
    if value is None:
        return None

    return _parse_datetime(value)


def _parse_labeled_int(text: str, label: str) -> int | None:
    value = _parse_labeled_value(text, label)
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _parse_labeled_bool(text: str, label: str) -> bool | None:
    value = _parse_labeled_value(text, label)
    if value is None:
        return None

    return _parse_registered(value.split(" ", 1)[0])


def _parse_registered_detail(text: str) -> tuple[bool | None, datetime | None]:
    match = re.search(
        r"Registrován:\s*(ano|ne)(?:,\s*(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}:\d{2}))?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None

    registered, registered_at = match.groups()
    return _parse_registered(registered.upper()), _parse_datetime(registered_at or "")


def _parse_labeled_value(text: str, label: str) -> str | None:
    pattern = re.escape(label) + r"\s*(.+?)(?=\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][^:]{1,80}:|$)"
    match = re.search(pattern, text)
    if not match:
        return None

    value = match.group(1).strip()
    return value or None


def _parse_between(text: str, start: str, end: str) -> str | None:
    match = re.search(re.escape(start) + r"\s*(.+?)\s*" + re.escape(end), text)
    if not match:
        return None

    value = match.group(1).strip()
    return value or None


def _parse_registration_window(text: str) -> tuple[datetime | None, datetime | None]:
    opens_at = None
    closes_at = None

    opens_match = re.search(
        r"od:\s*(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)",
        text,
    )
    closes_match = re.search(
        r"do:\s*(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)",
        text,
    )

    if opens_match:
        opens_at = _parse_datetime(opens_match.group(1))
    if closes_match:
        closes_at = _parse_datetime(closes_match.group(1))

    return opens_at, closes_at


def _parse_registered(text: str) -> bool | None:
    normalized = text.casefold()
    if normalized in {"ano", "a"}:
        return True
    if normalized in {"ne", "n"}:
        return False
    return None


def _parse_capacity(text: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"(\d+)/(\d+)", text)
    if not match:
        return None, None

    used, total = match.groups()
    return int(used), int(total)


def _can_register(info: str) -> bool | None:
    if not info:
        return None
    return "přihlásit" in info.casefold()


def _can_unregister(info: str) -> bool | None:
    if not info:
        return None
    return "zrušit registraci" in info.casefold() and "bylo možné" not in info.casefold()


def _find_link(node: Node, base_url: str, needle: str) -> str | None:
    for link in node.css("a"):
        href = link.attributes.get("href") or ""
        if needle in href:
            return urljoin(base_url, href)

    return None


def _page_text(tree: HTMLParser) -> str:
    if tree.body is None:
        return ""
    return re.sub(r"\s+", " ", tree.body.text(separator=" ", strip=True)).strip()


def _clean_text(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(strip=True)).strip()
