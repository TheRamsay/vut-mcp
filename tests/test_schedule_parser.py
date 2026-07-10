from datetime import datetime
from pathlib import Path

from vut_studis.parsers.schedule import parse_schedule_html

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_schedule_html_returns_deduplicated_typed_items() -> None:
    items = parse_schedule_html(
        (FIXTURES / "studis_schedule.html").read_text(),
        base_url="https://www.vut.cz/studis/student.phtml?sn=osobni_rozvrh",
    )

    assert len(items) == 2
    assert items[0].course_code == "ABC101"
    assert items[0].course_name == "Introduction to Systems"
    assert items[0].starts_at == datetime(2026, 9, 14, 8, 0)
    assert items[0].ends_at == datetime(2026, 9, 14, 9, 30)
    assert items[0].room == "R101"
    assert items[0].teacher == "Teacher One"
    assert items[0].kind == "Přednáška"
    assert (
        items[0].detail_url
        == "https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=101"
    )

    assert items[1].course_code == "DEF202"
    assert items[1].course_name == "Data Methods"
    assert items[1].starts_at == datetime(2026, 9, 17, 13, 0)
    assert items[1].ends_at == datetime(2026, 9, 17, 14, 0)
    assert items[1].kind == "Zkouška"
    assert (
        items[1].detail_url
        == "https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=202"
    )


def _single_row_schedule(href: str) -> str:
    return f"""
    <section data-date="18.09.2026"><table>
      <tr><th>Čas</th><th>Předmět</th></tr>
      <tr><td>10:00 - 11:00</td>
          <td><a href="{href}">GHI303</a> - Safe Parsing</td></tr>
    </table></section>
    """


def test_parse_schedule_html_keeps_only_exact_same_origin_course_detail_link() -> None:
    items = parse_schedule_html(
        _single_row_schedule("/studis/student.phtml?sn=predmet_detail&amp;apid=303"),
        base_url="https://www.vut.cz/studis/student.phtml?sn=osobni_rozvrh",
    )

    assert len(items) == 1
    assert (
        items[0].detail_url
        == "https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=303"
    )


def test_parse_schedule_html_discards_unsafe_or_unrelated_links() -> None:
    unsafe_hrefs = [
        "https://example.invalid/course",
        "javascript:alert('no')",
        "//example.invalid/course",
        "https://www.vut.cz@evil.invalid/course",
        "/studis/student.phtml?sn=ical_export",
    ]
    for href in unsafe_hrefs:
        items = parse_schedule_html(
            _single_row_schedule(href),
            base_url="https://www.vut.cz/studis/student.phtml?sn=osobni_rozvrh",
        )
        assert len(items) == 1
        assert items[0].detail_url is None


def test_parse_schedule_html_infers_academic_year_from_month_when_date_has_no_year() -> None:
    html = """
    <h2>Osobní rozvrh 2026/2027</h2>
    <h3>Pondělí 14. 9.</h3>
    <table><tr><th>Čas</th><th>Předmět</th></tr>
    <tr><td>08:00 - 09:00</td><td>ABC101 - Autumn class</td></tr></table>
    <h3>Pondělí 11. 1.</h3>
    <table><tr><th>Čas</th><th>Předmět</th></tr>
    <tr><td>08:00 - 09:00</td><td>DEF202 - Winter class</td></tr></table>
    """

    items = parse_schedule_html(html)

    assert [item.starts_at for item in items] == [
        datetime(2026, 9, 14, 8),
        datetime(2027, 1, 11, 8),
    ]
