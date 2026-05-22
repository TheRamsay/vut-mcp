from datetime import date

from vut_studis.models import CompletionType, CourseLanguage, CourseType, GradeValue
from vut_studis.parsers.grades import parse_grades_html


def test_parse_grades_html_extracts_course_grades() -> None:
    html = """
    <html>
      <body>
        <h2>Akademický rok: 2025/2026</h2>
        <h3>Zimní semestr, 1. ročník</h3>
        <table>
          <thead>
            <tr>
              <th>Zkr.</th><th>Název předmětu</th><th>Jazyk</th><th>Typ</th>
              <th>Kr.</th><th>VSP</th><th>Uk.</th><th>eL.</th>
              <th>Zápočet</th><th>Body</th><th>Známka</th><th>Termín</th><th>Absl.</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>ABC</td><td>Test Course</td><td>cs</td><td>P</td>
              <td>5</td><td></td><td>zk</td><td></td>
              <td>udělen</td><td>83,5</td><td>B(21.05.2026)</td><td>2</td><td>ano</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    grades = parse_grades_html(html)

    assert len(grades) == 1
    assert grades[0].course_code == "ABC"
    assert grades[0].course_name == "Test Course"
    assert grades[0].academic_year == "2025/2026"
    assert grades[0].semester == "Zimní semestr, 1. ročník"
    assert grades[0].language == CourseLanguage.CZECH
    assert grades[0].course_type == CourseType.REQUIRED
    assert grades[0].credits == 5
    assert grades[0].completion == CompletionType.EXAM
    assert grades[0].in_study_plan is None
    assert grades[0].elearning is None
    assert grades[0].points == 83.5
    assert grades[0].grade == GradeValue.B
    assert grades[0].grade_awarded_on == date(2026, 5, 21)
    assert grades[0].credit_awarded is True
    assert grades[0].credit_awarded_on is None
    assert grades[0].exam_term == 2
    assert grades[0].absolved is True
