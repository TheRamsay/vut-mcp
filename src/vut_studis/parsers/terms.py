from urllib.parse import parse_qs, urlsplit

from selectolax.parser import HTMLParser, Node

from vut_studis.models import CourseTerm, CourseTerms
from vut_studis.parsers.common import (
    can_register,
    can_unregister,
    clean_text,
    parse_capacity,
    parse_course_heading,
    parse_datetime,
    parse_float,
    parse_int,
    parse_numbered_name,
    parse_registration_window,
    same_origin_url,
)

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
    course_code, course_name, academic_year = parse_course_heading(tree)
    return CourseTerms(
        course_code=course_code,
        course_name=course_name,
        academic_year=academic_year,
        terms=_parse_terms(tree, base_url=base_url),
    )


def _parse_terms(tree: HTMLParser, *, base_url: str) -> list[CourseTerm]:
    for table in tree.css("table"):
        headers = {clean_text(header) for header in table.css("th")}
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
        headers = [clean_text(header) for header in row.css("th")]
        cells = [clean_text(cell) for cell in row.css("td")]

        if len(headers) == 1:
            assessment_order, assessment_name, assessment_category = parse_numbered_name(
                headers[0]
            )
            continue

        if len(cells) != 11:
            continue

        name, note = _parse_description(cells[1])
        used, total = parse_capacity(cells[7])
        opens_at, closes_at = parse_registration_window(cells[8])
        terms.append(
            CourseTerm(
                assessment_order=assessment_order,
                assessment_name=assessment_name,
                assessment_category=assessment_category,
                term_number=parse_int(cells[0].rstrip(".")),
                name=name,
                note=note,
                starts_at=parse_datetime(cells[2]),
                examiner=cells[3] or None,
                room=cells[4] or None,
                registered=_parse_registered(cells[6]),
                capacity_used=used,
                capacity_total=total,
                registration_info=cells[8] or None,
                registration_opens_at=opens_at,
                registration_closes_at=closes_at,
                can_register=can_register(cells[8]),
                can_unregister=can_unregister(cells[8]),
                max_points=parse_float(cells[9]),
                earned_points=parse_float(cells[10]),
                detail_url=_parse_detail_url(row, base_url),
            )
        )

    return terms


def _parse_description(text: str) -> tuple[str, str | None]:
    if "Pozn.:" not in text:
        return text, None

    name, note = text.split("Pozn.:", 1)
    return name.strip(), note.strip() or None


def _parse_registered(text: str) -> bool | None:
    if text == "ANO":
        return True
    if text == "NE":
        return False
    return None


def _parse_detail_url(row: Node, base_url: str) -> str | None:
    for link in row.css("a"):
        href = link.attributes.get("href") or ""
        url = same_origin_url(href, base_url)
        if url is None:
            continue
        parsed = urlsplit(url)
        if (
            parsed.path == "/studis/student.phtml"
            and parse_qs(parsed.query, keep_blank_values=True).get("sn") == ["termin_detail"]
        ):
            return url

    return None
