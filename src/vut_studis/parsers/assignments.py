import re
from datetime import datetime

from selectolax.parser import HTMLParser, Node

from vut_studis.models import AssignmentSubmissionFile, CourseAssignment, CourseAssignments
from vut_studis.parsers.common import (
    can_register,
    can_unregister,
    clean_text,
    find_link,
    parse_capacity,
    parse_course_heading,
    parse_datetime,
    parse_int,
    parse_numbered_name,
    parse_registration_window,
)

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
    course_code, course_name, academic_year = parse_course_heading(tree)
    return CourseAssignments(
        course_code=course_code,
        course_name=course_name,
        academic_year=academic_year,
        assignments=_parse_assignments(tree, base_url=base_url),
    )


def parse_assignment_detail_html(html: str, base_url: str = "") -> dict[str, object]:
    tree = HTMLParser(html)
    text = _page_text(tree)
    submission_url = find_link(tree, base_url, "sn=zadani_odevzdani")
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
        headers = {clean_text(header) for header in table.css("th")}
        if not {"Soubor", "Velikost", "Vloženo", "Vložil/a"}.issubset(headers):
            continue

        for row in table.css("tr"):
            cells = [clean_text(cell) for cell in row.css("td")]
            if len(cells) != 4:
                continue

            files.append(
                AssignmentSubmissionFile(
                    name=cells[0],
                    size=cells[1] or None,
                    uploaded_at=parse_datetime(cells[2]),
                    uploaded_by=cells[3] or None,
                    download_url=find_link(row, base_url, "zadani_soubor.php"),
                )
            )

    return files


def _parse_assignments(tree: HTMLParser, *, base_url: str) -> list[CourseAssignment]:
    for table in tree.css("table"):
        headers = {clean_text(header) for header in table.css("th")}
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
        headers = [clean_text(header) for header in row.css("th")]
        cells = [clean_text(cell) for cell in row.css("td")]

        if len(headers) == 1:
            assessment_order, assessment_name, assessment_category = parse_numbered_name(
                headers[0]
            )
            continue

        if len(cells) != 8:
            continue

        used, total = parse_capacity(cells[6])
        opens_at, closes_at = parse_registration_window(cells[7])
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
                can_register=can_register(cells[7]),
                can_unregister=can_unregister(cells[7]),
                detail_url=find_link(row, base_url, "sn=zadani_detail"),
            )
        )

    return assignments


def _parse_date_deadline(text: str) -> datetime | None:
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if not match:
        return None

    day, month, year = match.groups()
    return datetime(int(year), int(month), int(day), 23, 59, 59)


def _parse_labeled_datetime(text: str, label: str) -> datetime | None:
    value = _parse_labeled_value(text, label)
    if value is None:
        return None

    return parse_datetime(value)


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
    return _parse_registered(registered.upper()), parse_datetime(registered_at or "")


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


def _parse_registered(text: str) -> bool | None:
    normalized = text.casefold()
    if normalized in {"ano", "a"}:
        return True
    if normalized in {"ne", "n"}:
        return False
    return None


def _page_text(tree: HTMLParser) -> str:
    if tree.body is None:
        return ""
    return re.sub(r"\s+", " ", tree.body.text(separator=" ", strip=True)).strip()
