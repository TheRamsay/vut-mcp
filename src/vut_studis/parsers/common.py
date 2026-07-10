import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

from vut_studis.models import CompletionType


def clean_text(node: Node) -> str:
    return re.sub(r"\s+", " ", node.text(strip=True)).strip()


def blank_to_none(text: str) -> str | None:
    text = text.strip()
    return text or None


def parse_float(text: str) -> float | None:
    value = blank_to_none(text)
    if value is None:
        return None

    value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(text: str) -> int | None:
    value = blank_to_none(text)
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def parse_completion(text: str) -> CompletionType | None:
    normalized = text.strip().casefold()
    labels = {
        "zápočet": CompletionType.CREDIT,
        "zkouška": CompletionType.EXAM,
        "zápočet a zkouška": CompletionType.CREDIT_AND_EXAM,
        "klasifikovaný zápočet": CompletionType.CLASSIFIED_CREDIT,
        "uznaná zkouška": CompletionType.RECOGNIZED_EXAM,
        "uznaný klasifikovaný zápočet": CompletionType.RECOGNIZED_CLASSIFIED_CREDIT,
    }
    return labels.get(normalized) or parse_enum(CompletionType, text)


def parse_enum[T: str](enum_type: type[T], text: str) -> T | None:
    value = blank_to_none(text)
    if value is None:
        return None

    try:
        return enum_type(value)
    except ValueError:
        return None


def parse_course_heading(tree: HTMLParser) -> tuple[str, str | None, str | None]:
    for heading in tree.css("h3, h2"):
        text = clean_text(heading)
        match = re.fullmatch(r"([A-Za-z0-9-]+)\s+-\s+(.+?)\(a\.r\.(\d{4}/\d{4})\)", text)
        if match:
            course_code, course_name, academic_year = match.groups()
            return course_code, course_name.strip(), academic_year

    return "", None, None


def parse_numbered_name(text: str) -> tuple[int | None, str, str | None]:
    match = re.fullmatch(r"(\d+)\.\s+(.+?)(?:\s+\(([^()]*)\))?", text)
    if not match:
        return None, text, None

    order, name, category = match.groups()
    return int(order), name, category


def parse_datetime(text: str) -> datetime | None:
    match = re.fullmatch(
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        text,
    )
    if not match:
        return None

    day, month, year, hour, minute, second = match.groups()
    return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0))


def parse_registration_window(text: str) -> tuple[datetime | None, datetime | None]:
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
        opens_at = parse_datetime(opens_match.group(1))
    if closes_match:
        closes_at = parse_datetime(closes_match.group(1))

    return opens_at, closes_at


def parse_capacity(text: str) -> tuple[int | None, int | None]:
    match = re.fullmatch(r"(\d+)/(\d+)", text)
    if not match:
        return None, None

    used, total = match.groups()
    return int(used), int(total)


def can_register(info: str) -> bool | None:
    if not info:
        return None
    return "přihlásit" in info.casefold()


def can_unregister(info: str) -> bool | None:
    if not info:
        return None
    return "zrušit registraci" in info.casefold() and "bylo možné" not in info.casefold()


def find_link(node: Node, base_url: str, needle: str) -> str | None:
    for link in node.css("a"):
        href = link.attributes.get("href") or ""
        if needle in href:
            return same_origin_url(href, base_url)

    return None


def same_origin_url(href: str, base_url: str) -> str | None:
    """Resolve one HTTP(S) link only when it has the exact base origin."""
    href = href.strip()
    base = urlsplit(base_url)
    if not href or base.scheme not in {"http", "https"} or not base.netloc:
        return None

    url = urljoin(base_url, href)
    target = urlsplit(url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        return None

    return url
