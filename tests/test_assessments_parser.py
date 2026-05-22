from datetime import date

from vut_studis.parsers.assessments import parse_course_assessment_html


def test_parse_course_assessment_html_extracts_rules() -> None:
    html = """
    <html>
      <body>
        <h3>ABC - Test Course(a.r.2025/2026)</h3>
        <table>
          <tr>
            <th>Název</th>
            <th>Poř. č.</th>
            <th>Min bodů</th>
            <th>Max bodů</th>
            <th>Body</th>
            <th>Povinnost</th>
            <th>Celk. hodn.</th>
            <th>Splněno</th>
            <th>Zpr. hodn.</th>
            <th>Datum</th>
            <th>Hodnotil</th>
          </tr>
          <tr>
            <th>1. Project (projekty)</th>
            <th></th>
            <th>10</th>
            <th>20</th>
            <th>18.5</th>
            <th>ano</th>
            <th>ano</th>
            <th></th>
            <th></th>
            <th></th>
            <th></th>
          </tr>
          <tr>
              <td>
                Project submission
                <a href="www_base/zprava.php?zprava_id=1&amp;skupina=dilci-hodnoceni"></a>
              </td>
            <td>1</td>
            <td></td>
            <td></td>
            <td>18.5</td>
            <td></td>
            <td>ano</td>
            <td></td>
            <td></td>
            <td>21.05.2026</td>
            <td>Teacher Name</td>
          </tr>
          <tr>
            <td>Project note text.</td>
          </tr>
        </table>
      </body>
    </html>
    """

    assessment = parse_course_assessment_html(
        html,
        base_url="https://www.vut.cz/studis/student.phtml?sn=predmet_detail&apid=123",
    )

    assert assessment.course_code == "ABC"
    assert assessment.course_name == "Test Course"
    assert assessment.academic_year == "2025/2026"
    assert assessment.completion is None
    assert len(assessment.items) == 1
    assert assessment.items[0].name == "Project"
    assert assessment.items[0].category == "projekty"
    assert assessment.items[0].min_points == 10
    assert assessment.items[0].max_points == 20
    assert assessment.items[0].points == 18.5
    assert assessment.items[0].required is True
    assert assessment.items[0].total_evaluation is True
    assert assessment.items[0].notes == ["Project note text."]
    assert len(assessment.items[0].entries) == 1
    assert assessment.items[0].entries[0].name == "Project submission"
    assert assessment.items[0].entries[0].points == 18.5
    assert assessment.items[0].entries[0].awarded_on == date(2026, 5, 21)
    assert (
        assessment.items[0].entries[0].message_url
        == "https://www.vut.cz/studis/www_base/zprava.php?zprava_id=1&skupina=dilci-hodnoceni"
    )
