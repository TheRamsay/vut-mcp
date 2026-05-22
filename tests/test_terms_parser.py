from datetime import datetime

from vut_studis.parsers.terms import parse_course_terms_html


def test_parse_course_terms_html_extracts_registration_status() -> None:
    html = """
    <html>
      <body>
        <h3>ABC - Test Course(a.r.2025/2026)</h3>
        <table>
          <tr>
            <th>Termín</th><th>Registrován</th><th>Hodnocení</th>
          </tr>
          <tr>
            <th>č.</th><th>Popis</th><th>Začátek</th><th>Zkoušející</th><th>Místnost</th>
            <th>El</th><th>Registrován</th><th>Obs./max.</th><th>Informace</th>
            <th>Max bodů</th><th>Získané</th>
          </tr>
          <tr><th>7. Exam (zkouška)</th></tr>
          <tr>
            <td><a href="student.phtml?sn=termin_detail&amp;tid=1">1.</a></td>
            <td>1. termínPozn.: Bring ID.</td>
            <td>18.5.2026 9:00</td>
            <td>Teacher Name</td>
            <td>D105</td>
            <td></td>
            <td>ANO</td>
            <td>10/20</td>
            <td>od: 17.5.2026 9:00 do: 18.5.2026 9:00</td>
            <td>51</td>
            <td>44</td>
          </tr>
          <tr>
            <td>2.</td>
            <td>2. termín</td>
            <td>1.6.2026 9:00</td>
            <td>Teacher Name</td>
            <td>D105</td>
            <td></td>
            <td>NE</td>
            <td>12/20</td>
            <td>přihlásit</td>
            <td>51</td>
            <td></td>
          </tr>
        </table>
      </body>
    </html>
    """

    terms = parse_course_terms_html(
        html,
        base_url="https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=123",
    )

    assert terms.course_code == "ABC"
    assert terms.course_name == "Test Course"
    assert terms.academic_year == "2025/2026"
    assert len(terms.terms) == 2
    assert terms.terms[0].assessment_order == 7
    assert terms.terms[0].assessment_name == "Exam"
    assert terms.terms[0].assessment_category == "zkouška"
    assert terms.terms[0].term_number == 1
    assert terms.terms[0].note == "Bring ID."
    assert terms.terms[0].starts_at == datetime(2026, 5, 18, 9, 0)
    assert terms.terms[0].registered is True
    assert terms.terms[0].capacity_used == 10
    assert terms.terms[0].capacity_total == 20
    assert terms.terms[0].registration_opens_at == datetime(2026, 5, 17, 9, 0)
    assert terms.terms[0].registration_closes_at == datetime(2026, 5, 18, 9, 0)
    assert terms.terms[0].can_unregister is False
    assert terms.terms[0].max_points == 51
    assert terms.terms[0].earned_points == 44
    assert (
        terms.terms[0].detail_url
        == "https://www.vut.cz/studis/student.phtml?sn=termin_detail&tid=1"
    )
    assert terms.terms[1].registered is False
    assert terms.terms[1].can_register is True
