from datetime import datetime

from vut_studis.parsers.assignments import (
    parse_assignment_detail_html,
    parse_assignment_submission_html,
    parse_course_assignments_html,
)


def test_parse_course_assignments_html_extracts_assignment_rows() -> None:
    html = """
    <html>
      <body>
        <h3>ABC - Test Course(a.r.2025/2026)</h3>
        <table>
          <tr><th>zadání</th><th>registrován</th></tr>
          <tr>
            <th>č.</th><th>název</th><th>vedoucí</th><th>popis</th>
            <th>odevzdání</th><th>registrován</th><th>obs./max.</th><th>informace</th>
          </tr>
          <tr><th>2. Project (projekty)</th></tr>
          <tr>
            <td><a href="student.phtml?sn=zadani_detail&amp;zid=1">1.</a></td>
            <td>Project submission</td>
            <td>Teacher Name</td>
            <td>Submit archive.</td>
            <td>24.4.2026</td>
            <td>ANO</td>
            <td>10/20</td>
            <td>Zrušit registraci</td>
          </tr>
        </table>
      </body>
    </html>
    """

    assignments = parse_course_assignments_html(
        html,
        base_url="https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=123",
    )

    assert assignments.course_code == "ABC"
    assert assignments.course_name == "Test Course"
    assert assignments.academic_year == "2025/2026"
    assert len(assignments.assignments) == 1
    assignment = assignments.assignments[0]
    assert assignment.assessment_order == 2
    assert assignment.assessment_name == "Project"
    assert assignment.assessment_category == "projekty"
    assert assignment.assignment_number == 1
    assert assignment.name == "Project submission"
    assert assignment.teacher == "Teacher Name"
    assert assignment.submit_until == datetime(2026, 4, 24, 23, 59, 59)
    assert assignment.registered is True
    assert assignment.capacity_used == 10
    assert assignment.capacity_total == 20
    assert assignment.can_unregister is True
    assert assignment.detail_url == "https://www.vut.cz/studis/student.phtml?sn=zadani_detail&zid=1"


def test_parse_assignment_detail_html_extracts_submission_metadata() -> None:
    html = """
    <html>
      <body>
        Detail zadání
        Předmět: ABC - Test Course
        Název: Project submission
        Vedoucí: Teacher Name
        Popis: Submit archive.
        Registrace zadání (registrován)
        Registrovat od: 02.02.2026 08:00:00
        Registrovat do: 23.02.2026 23:59:59
        Registraci lze zrušit do: 23.02.2026 23:59:59
        Zadání odevzdat do: 24.04.2026 23:59:59
        Aktuálně přihlášených: 10
        Maximum studentů: 20
        Registrován: ano, 03.02.2026 04:27:00 (potvrzená registrace)
        Přihlášení automaticky: ano
        <a href="student.phtml?sn=zadani_odevzdani&amp;registrace_zadani_id=1">
          Odevzdání souborů
        </a>
      </body>
    </html>
    """

    detail = parse_assignment_detail_html(
        html,
        base_url="https://www.vut.cz/studis/student.phtml?sn=zadani_detail&zid=1",
    )

    assert detail["description"] == "Submit archive."
    assert detail["registration_opens_at"] == datetime(2026, 2, 2, 8, 0)
    assert detail["registration_closes_at"] == datetime(2026, 2, 23, 23, 59, 59)
    assert detail["unregistration_closes_at"] == datetime(2026, 2, 23, 23, 59, 59)
    assert detail["submit_until"] == datetime(2026, 4, 24, 23, 59, 59)
    assert detail["capacity_used"] == 10
    assert detail["capacity_total"] == 20
    assert detail["registered"] is True
    assert detail["registered_at"] == datetime(2026, 2, 3, 4, 27)
    assert detail["auto_registration"] is True
    assert (
        detail["submission_url"]
        == "https://www.vut.cz/studis/student.phtml?sn=zadani_odevzdani&registrace_zadani_id=1"
    )


def test_parse_assignment_submission_html_extracts_uploaded_files() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr><th>Soubor</th><th>Velikost</th><th>Vloženo</th><th>Vložil/a</th></tr>
          <tr>
            <td><a href="zadani_soubor.php?id=1">solution.zip</a></td>
            <td>30.82 kB</td>
            <td>24.04.2026 20:48:35</td>
            <td>Student Name</td>
          </tr>
        </table>
      </body>
    </html>
    """

    files = parse_assignment_submission_html(
        html,
        base_url="https://www.vut.cz/studis/student.phtml?sn=zadani_odevzdani",
    )

    assert len(files) == 1
    assert files[0].name == "solution.zip"
    assert files[0].size == "30.82 kB"
    assert files[0].uploaded_at == datetime(2026, 4, 24, 20, 48, 35)
    assert files[0].uploaded_by == "Student Name"
    assert files[0].download_url == "https://www.vut.cz/studis/zadani_soubor.php?id=1"
