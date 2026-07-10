from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from vut_studis.models import CourseUpdate, CourseUpdates
from vut_studis.parsers.course_updates import parse_course_updates_html

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "studis_course_updates.html"
BASE_URL = "https://www.vut.cz/studis/student.phtml?sn=aktuality_predmet"


def test_parse_course_updates_html_extracts_safe_metadata() -> None:
    updates = parse_course_updates_html(FIXTURE_PATH.read_text(), base_url=BASE_URL)

    assert updates.truncated_count == 0
    assert len(updates.items) == 2

    newest, older = updates.items
    assert newest.published_at == datetime(2026, 7, 9, 10, 20, 30)
    assert newest.title == "Změna místnosti"
    assert newest.course_code == "DEF202"
    assert newest.course_name == "Bezpečné systémy"
    assert newest.author == "Vyučující Beta"
    assert newest.url is None
    assert newest.course_url is None

    assert older.published_at == datetime(2026, 7, 8, 9, 15)
    assert older.title == "Podklady k semináři"
    assert older.course_code == "ABC101"
    assert older.course_name == "Anonymní analýza"
    assert older.url == "https://www.vut.cz/studis/student.phtml?sn=aktualita_detail&id=7"
    assert older.course_url == "https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=42"


def test_course_update_models_are_frozen_and_have_result_defaults() -> None:
    update = CourseUpdate(
        id="test-update",
        published_at=datetime(2026, 7, 9, 10, 20),
        title="Test update",
        course_code="ABC101",
        course_name="Test course",
        author="Test author",
    )

    with pytest.raises(ValidationError):
        update.title = "Changed"

    assert CourseUpdates().items == []
    assert CourseUpdates().truncated_count == 0


def test_parse_course_updates_html_rejects_protocol_relative_and_non_http_links() -> None:
    html = """
    <table>
      <tr><th>Vystavil</th><th>Aktualita</th><th>Datum</th><th>Předmět</th></tr>
      <tr>
        <td>Test author</td>
        <td><a href="//evil.invalid/notice">External notice</a></td>
        <td>9.7.2026 10:20</td>
        <td><a href="data:text/plain,unsafe">ABC101 - Test course</a></td>
      </tr>
    </table>
    """

    updates = parse_course_updates_html(html, base_url=BASE_URL)

    assert len(updates.items) == 1
    assert updates.items[0].url is None
    assert updates.items[0].course_url is None
