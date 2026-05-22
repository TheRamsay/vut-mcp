import re
from datetime import date

from selectolax.parser import HTMLParser, Node

from vut_studis.models import CompletionType, CourseLanguage, CourseType, Grade, GradeValue

GRADE_TABLE_HEADERS = {
    "Zkr.",
    "Název předmětu",
    "Jazyk",
    "Typ",
    "Kr.",
    "VSP",
    "Uk.",
    "eL.",
    "Zápočet",
    "Body",
    "Známka",
    "Termín",
    "Absl.",
}


def parse_grades_html(html: str) -> list[Grade]:
    tree = HTMLParser(html)
    grades: list[Grade] = []
    academic_year: str | None = None
    semester: str | None = None

    for node in tree.css("h2, h3, table"):
        text = _clean_text(node)
        if node.tag == "h2":
            academic_year = _parse_academic_year(text) or academic_year
            continue

        if node.tag == "h3":
            parsed_semester = _parse_semester(text)
            if parsed_semester:
                semester = parsed_semester
            parsed_year = _parse_academic_year(text)
            if parsed_year:
                academic_year = parsed_year
            continue

        if node.tag == "table" and _is_grade_table(node):
            grades.extend(_parse_grade_table(node, academic_year=academic_year, semester=semester))

    return grades


def _is_grade_table(table: Node) -> bool:
    headers = {_clean_text(header) for header in table.css("th")}
    return GRADE_TABLE_HEADERS.issubset(headers)


def _parse_grade_table(
    table: Node,
    *,
    academic_year: str | None,
    semester: str | None,
) -> list[Grade]:
    grades: list[Grade] = []

    for row in table.css("tr"):
        cells = [_clean_text(cell) for cell in row.css("td")]
        if len(cells) != 13:
            continue

        credit_awarded, credit_awarded_on = _parse_status_date(cells[8])
        grade, grade_awarded_on = _parse_grade(cells[10])
        grades.append(
            Grade(
                course_code=_blank_to_none(cells[0]),
                course_name=cells[1],
                language=_parse_enum(CourseLanguage, cells[2]),
                course_type=_parse_enum(CourseType, cells[3]),
                credits=_parse_float(cells[4]),
                in_study_plan=_parse_bool(cells[5]),
                completion=_parse_enum(CompletionType, cells[6]),
                elearning=_parse_bool(cells[7]),
                credit_awarded=credit_awarded,
                credit_awarded_on=credit_awarded_on,
                points=_parse_float(cells[9]),
                grade=grade,
                grade_awarded_on=grade_awarded_on,
                exam_term=_parse_int(cells[11]),
                absolved=_parse_bool(cells[12]),
                academic_year=academic_year,
                semester=semester,
            )
        )

    return grades


def _clean_text(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(strip=True)).strip()


def _parse_academic_year(text: str) -> str | None:
    match = re.search(r"Akademický rok:\s*(\d{4}/\d{4})", text)
    if match:
        return match.group(1)
    return None


def _parse_semester(text: str) -> str | None:
    if "Zimní semestr" in text:
        return text
    if "Letní semestr" in text:
        return text
    return None


def _parse_float(text: str) -> float | None:
    value = _blank_to_none(text)
    if value is None:
        return None

    value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(text: str) -> int | None:
    value = _blank_to_none(text)
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _parse_bool(text: str) -> bool | None:
    value = _blank_to_none(text)
    if value is None:
        return None

    normalized = value.casefold()
    if normalized in {"ano", "udělen"}:
        return True
    if normalized == "ne":
        return False
    return None


def _parse_grade(text: str) -> tuple[GradeValue | None, date | None]:
    value = _blank_to_none(text)
    if value is None:
        return None, None

    match = re.fullmatch(r"(.+?)\((\d{2})\.(\d{2})\.(\d{4})\)", value)
    if not match:
        return _parse_enum(GradeValue, value), None

    grade, day, month, year = match.groups()
    return _parse_enum(GradeValue, grade), date(int(year), int(month), int(day))


def _parse_status_date(text: str) -> tuple[bool | None, date | None]:
    value = _blank_to_none(text)
    if value is None:
        return None, None

    match = re.fullmatch(r"(.+?)\((\d{2})\.(\d{2})\.(\d{4})\)", value)
    if not match:
        return _parse_bool(value), None

    status, day, month, year = match.groups()
    return _parse_bool(status), date(int(year), int(month), int(day))


def _parse_enum[T: str](enum_type: type[T], text: str) -> T | None:
    value = _blank_to_none(text)
    if value is None:
        return None

    try:
        return enum_type(value)
    except ValueError:
        return None


def _blank_to_none(text: str) -> str | None:
    text = text.strip()
    return text or None
