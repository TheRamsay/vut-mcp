import re
from datetime import date, datetime
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

from vut_studis.models import (
    AssessmentEntry,
    AssessmentItem,
    AssessmentMessage,
    CompletionType,
    CourseAssessment,
)
from vut_studis.parsers.common import (
    clean_text,
    parse_completion,
    parse_course_heading,
    parse_float,
    parse_int,
    parse_numbered_name,
)

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
    course_code, course_name, academic_year = _parse_assessment_course_heading(tree)

    return CourseAssessment(
        course_code=course_code,
        course_name=course_name,
        academic_year=academic_year,
        credits=parse_float(_parse_label_value(tree, "Počet kreditů:") or ""),
        completion=_parse_completion(tree),
        items=_parse_assessment_items(tree, base_url=base_url),
    )


def parse_assessment_message_html(
    html: str,
    *,
    url: str,
    course_code: str,
    course_name: str | None = None,
    item_order: int | None = None,
    item_name: str | None = None,
    entry_order: int | None = None,
    entry_name: str | None = None,
) -> AssessmentMessage:
    tree = HTMLParser(html)
    labels = _parse_message_labels(tree)
    body = _parse_message_body(tree, labels)

    return AssessmentMessage(
        course_code=course_code,
        course_name=course_name,
        item_order=item_order,
        item_name=item_name,
        entry_order=entry_order,
        entry_name=entry_name,
        title=_parse_message_title(tree),
        subject=_first_label(labels, "Předmět", "Subject", "Název"),
        sender=_first_label(labels, "Od", "Odesílatel", "Autor", "From"),
        sent_at=_parse_message_datetime(_first_label(labels, "Datum", "Odesláno", "Vloženo")),
        body=body,
        url=url,
    )


def _parse_assessment_items(tree: HTMLParser, *, base_url: str) -> list[AssessmentItem]:
    for table in tree.css("table"):
        headers = {clean_text(header) for header in table.css("th")}
        if not ASSESSMENT_HEADERS.issubset(headers):
            continue

        return _parse_assessment_table(table, base_url=base_url)

    return []


def _parse_assessment_table(table: Node, *, base_url: str) -> list[AssessmentItem]:
    items: list[AssessmentItem] = []
    current_item: AssessmentItem | None = None

    for row in table.css("tr"):
        headers = [clean_text(header) for header in row.css("th")]
        cells = [clean_text(cell) for cell in row.css("td")]

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
    order, name, category = parse_numbered_name(cells[0])
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


def _parse_assessment_course_heading(tree: HTMLParser) -> tuple[str, str | None, str | None]:
    course_code, course_name, academic_year = parse_course_heading(tree)
    if course_code:
        return course_code, course_name, academic_year

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

        if clean_text(headers[0]) == label:
            value = clean_text(cells[0])
            return value or None

    return None


def _parse_legacy_course_name(tree: HTMLParser) -> str | None:
    for heading in tree.css("h2"):
        text = clean_text(heading)
        if "karta na webu fakulty" in text:
            return re.sub(r"\s*\(karta na webu fakulty\)\s*$", "", text)
    return None


def _parse_completion(tree: HTMLParser) -> CompletionType | None:
    return parse_completion(_parse_label_value(tree, "Ukončení:") or "")


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


def _parse_message_title(tree: HTMLParser) -> str | None:
    for selector in ("h1", "h2", "h3", "title"):
        node = tree.css_first(selector)
        if node is None:
            continue
        title = clean_text(node)
        if title:
            return title
    return None


def _parse_message_labels(tree: HTMLParser) -> dict[str, str]:
    labels: dict[str, str] = {}

    for row in tree.css("tr"):
        headers = row.css("th")
        cells = row.css("td")
        if len(headers) != 1 or len(cells) != 1:
            continue

        label = _clean_label(headers[0])
        value = clean_text(cells[0])
        if label and value:
            labels[label] = value

    for row in tree.css("dl"):
        labels_by_term = row.css("dt")
        values = row.css("dd")
        for term, value_node in zip(labels_by_term, values, strict=False):
            label = _clean_label(term)
            value = clean_text(value_node)
            if label and value:
                labels[label] = value

    return labels


def _parse_message_body(tree: HTMLParser, labels: dict[str, str]) -> str:
    for label in ("Zpráva", "Text zprávy", "Text", "Message", "Poznámka"):
        value = labels.get(label)
        if value:
            return value

    for selector in ("#obsah", ".obsah", ".zprava", ".message", "article"):
        node = tree.css_first(selector)
        if node is None:
            continue
        text = clean_text(node)
        if text:
            return text

    return clean_text(tree.body) if tree.body is not None else clean_text(tree.root)


def _first_label(labels: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = labels.get(name)
        if value:
            return value
    return None


def _parse_message_datetime(text: str | None) -> datetime | None:
    if text is None:
        return None

    match = re.search(
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
        text,
    )
    if not match:
        return None

    day, month, year, hour, minute, second = match.groups()
    return datetime(
        int(year),
        int(month),
        int(day),
        int(hour or 0),
        int(minute or 0),
        int(second or 0),
    )


def _parse_message_url(row: Node, base_url: str) -> str | None:
    for link in row.css("a"):
        href = link.attributes.get("href") or ""
        if "zprava.php" in href and "skupina=dilci-hodnoceni" in href:
            return urljoin(base_url, href)

    return None


def _clean_label(node: Node) -> str:
    return clean_text(node).rstrip(":").strip()
