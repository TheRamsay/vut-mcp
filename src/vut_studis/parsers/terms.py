import re
from datetime import datetime
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from vut_studis.models import CourseTerm, CourseTerms
from vut_studis.parsers.grades import parse_float, parse_int

TERMS_HEADERS = {
    "č.",
    "Popis",
    "Začátek",
    "Zkoušející",
    "Místnost",
    "Registrován",
    "Obs./max.",
    "Informace",
    "Max bodů",
    "Získané",
}


def parse_course_terms_html(html: str, base_url: str = "") -> CourseTerms:
    tree = HTMLParser(html)
    course_code, course_name, academic_year = _parse_course_heading(tree)
    return CourseTerms(
        course_code=course_code,
        course_name=course_name,
        academic_year=academic_year,
        terms=_parse_terms(tree, base_url=base_url),
    )


def _parse_terms(tree: HTMLParser, *, base_url: str) -> list[CourseTerm]:
    for table in tree.css("table"):
        headers = {_clean_text(header) for header in table.css("th")}
        if not TERMS_HEADERS.issubset(headers):
            continue

        return _parse_terms_table(table, base_url=base_url)

    return []


def _parse_terms_table(table: Node, *, base_url: str) -> list[CourseTerm]:
    terms: list[CourseTerm] = []
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

        if len(cells) != 11:
            continue

        name, note = _parse_description(cells[1])
        used, total = _parse_capacity(cells[7])
        opens_at, closes_at = _parse_registration_window(cells[8])
        terms.append(
            CourseTerm(
                assessment_order=assessment_order,
                assessment_name=assessment_name,
                assessment_category=assessment_category,
                term_number=parse_int(cells[0].rstrip(".")),
                name=name,
                note=note,
                starts_at=_parse_datetime(cells[2]),
                examiner=cells[3] or None,
                room=cells[4] or None,
                registered=_parse_registered(cells[6]),
                capacity_used=used,
                capacity_total=total,
                registration_info=cells[8] or None,
                registration_opens_at=opens_at,
                registration_closes_at=closes_at,
                can_register=_can_register(cells[8]),
                can_unregister=_can_unregister(cells[8]),
                max_points=parse_float(cells[9]),
                earned_points=parse_float(cells[10]),
                detail_url=_parse_detail_url(row, base_url),
            )
        )

    return terms


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


def _parse_description(text: str) -> tuple[str, str | None]:
    if "Pozn.:" not in text:
        return text, None

    name, note = text.split("Pozn.:", 1)
    return name.strip(), note.strip() or None


def _parse_datetime(text: str) -> datetime | None:
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})", text)
    if not match:
        return None

    day, month, year, hour, minute = match.groups()
    return datetime(int(year), int(month), int(day), int(hour), int(minute))


def _parse_registration_window(text: str) -> tuple[datetime | None, datetime | None]:
    opens_at = None
    closes_at = None

    opens_match = re.search(
        r"od:\s*(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2})",
        text,
    )
    closes_match = re.search(
        r"do:\s*(\d{1,2}\.\d{1,2}\.\d{4}\s+\d{1,2}:\d{2})",
        text,
    )

    if opens_match:
        opens_at = _parse_datetime(opens_match.group(1))
    if closes_match:
        closes_at = _parse_datetime(closes_match.group(1))

    return opens_at, closes_at


def _parse_registered(text: str) -> bool | None:
    if text == "ANO":
        return True
    if text == "NE":
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


def _parse_detail_url(row: Node, base_url: str) -> str | None:
    for link in row.css("a"):
        href = link.attributes.get("href") or ""
        if "sn=termin_detail" in href:
            return urljoin(base_url, href)

    return None


def _clean_text(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(strip=True)).strip()
