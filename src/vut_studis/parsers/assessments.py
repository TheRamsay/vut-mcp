import re
from datetime import date
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from vut_studis.models import AssessmentEntry, AssessmentItem, CompletionType, CourseAssessment
from vut_studis.parsers.grades import parse_completion, parse_float, parse_int

ASSESSMENT_HEADERS = {
    "Název",
    "Poř. č.",
    "Min bodů",
    "Max bodů",
    "Body",
    "Povinnost",
    "Celk. hodn.",
    "Splněno",
    "Zpr. hodn.",
    "Datum",
    "Hodnotil",
}


def parse_course_assessment_html(html: str, base_url: str = "") -> CourseAssessment:
    tree = HTMLParser(html)
    course_code, course_name, academic_year = _parse_course_heading(tree)

    return CourseAssessment(
        course_code=course_code,
        course_name=course_name,
        academic_year=academic_year,
        credits=parse_float(_parse_label_value(tree, "Počet kreditů:") or ""),
        completion=_parse_completion(tree),
        items=_parse_assessment_items(tree, base_url=base_url),
    )


def _parse_assessment_items(tree: HTMLParser, *, base_url: str) -> list[AssessmentItem]:
    for table in tree.css("table"):
        headers = {_clean_text(header) for header in table.css("th")}
        if not ASSESSMENT_HEADERS.issubset(headers):
            continue

        return _parse_assessment_table(table, base_url=base_url)

    return []


def _parse_assessment_table(table: Node, *, base_url: str) -> list[AssessmentItem]:
    items: list[AssessmentItem] = []
    current_item: AssessmentItem | None = None

    for row in table.css("tr"):
        headers = [_clean_text(header) for header in row.css("th")]
        cells = [_clean_text(cell) for cell in row.css("td")]

        if headers and headers[0] == "Název":
            continue

        if len(headers) == 11:
            current_item = _parse_parent_item(headers, row=row, base_url=base_url)
            items.append(current_item)
            continue

        if current_item is None:
            continue

        if len(cells) == 1 and cells[0]:
            current_item.notes.append(cells[0])
            continue

        if len(cells) == 11:
            current_item.entries.append(_parse_entry(cells, row=row, base_url=base_url))

    return items


def _parse_parent_item(cells: list[str], *, row: Node, base_url: str) -> AssessmentItem:
    order, name, category = _parse_numbered_name(cells[0])
    return AssessmentItem(
        order=order,
        name=name,
        category=category,
        min_points=parse_float(cells[2]),
        max_points=parse_float(cells[3]),
        points=parse_float(cells[4]),
        required=_parse_required(cells[5]),
        total_evaluation=_parse_bool(cells[6]),
        fulfilled=_parse_bool(cells[7]),
        reported=_parse_bool(cells[8]),
        awarded_on=_parse_date(cells[9]),
        evaluated_by=cells[10] or None,
        message_url=_parse_message_url(row, base_url),
    )


def _parse_entry(cells: list[str], *, row: Node, base_url: str) -> AssessmentEntry:
    return AssessmentEntry(
        name=cells[0],
        order=parse_int(cells[1]),
        points=parse_float(cells[4]),
        total_evaluation=_parse_bool(cells[6]),
        fulfilled=_parse_bool(cells[7]),
        reported=_parse_bool(cells[8]),
        awarded_on=_parse_date(cells[9]),
        evaluated_by=cells[10] or None,
        message_url=_parse_message_url(row, base_url),
    )


def _parse_course_heading(tree: HTMLParser) -> tuple[str, str | None, str | None]:
    for heading in tree.css("h3, h2"):
        text = _clean_text(heading)
        match = re.fullmatch(r"([A-Za-z0-9-]+)\s+-\s+(.+?)\(a\.r\.(\d{4}/\d{4})\)", text)
        if match:
            course_code, course_name, academic_year = match.groups()
            return course_code, course_name.strip(), academic_year

    return (
        _parse_label_value(tree, "Zkratka předmětu:") or "",
        _parse_legacy_course_name(tree),
        None,
    )


def _parse_label_value(tree: HTMLParser, label: str) -> str | None:
    for row in tree.css("tr"):
        headers = row.css("th")
        cells = row.css("td")
        if len(headers) != 1 or len(cells) != 1:
            continue

        if _clean_text(headers[0]) == label:
            value = _clean_text(cells[0])
            return value or None

    return None


def _parse_legacy_course_name(tree: HTMLParser) -> str | None:
    for heading in tree.css("h2"):
        text = _clean_text(heading)
        if "karta na webu fakulty" in text:
            return re.sub(r"\s*\(karta na webu fakulty\)\s*$", "", text)
    return None


def _parse_completion(tree: HTMLParser) -> CompletionType | None:
    return parse_completion(_parse_label_value(tree, "Ukončení:") or "")


def _parse_numbered_name(text: str) -> tuple[int | None, str, str | None]:
    match = re.fullmatch(r"(\d+)\.\s+(.+?)(?:\s+\(([^()]*)\))?", text)
    if not match:
        return None, text, None

    order, name, category = match.groups()
    return int(order), name, category


def _parse_required(text: str) -> bool | None:
    if text == "povinný" or text == "ano":
        return True
    if text == "nepovinný" or text == "ne":
        return False
    return None


def _parse_bool(text: str) -> bool | None:
    if text == "ano":
        return True
    if text == "ne":
        return False
    return None


def _parse_date(text: str) -> date | None:
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if not match:
        return None

    day, month, year = match.groups()
    return date(int(year), int(month), int(day))


def _parse_message_url(row: Node, base_url: str) -> str | None:
    for link in row.css("a"):
        href = link.attributes.get("href") or ""
        if "zprava.php" in href and "skupina=dilci-hodnoceni" in href:
            return urljoin(base_url, href)

    return None


def _clean_text(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(strip=True)).strip()
