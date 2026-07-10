from datetime import datetime

from vut_studis.aggregates import build_assessment_dashboard
from vut_studis.models import AssessmentDashboard, AssessmentDashboardItem, CourseTerm, CourseTerms

NOW = datetime(2026, 5, 22, 12, 0)


def _course_terms(course_code: str, *terms: CourseTerm) -> CourseTerms:
    return CourseTerms(
        course_code=course_code,
        course_name=f"{course_code} Course",
        terms=list(terms),
    )


def test_assessment_dashboard_models_retain_read_only_term_metadata() -> None:
    item = AssessmentDashboardItem(
        course_code="ABC",
        course_name="Test Course",
        assessment_name="Exam",
        assessment_category="zkouška",
        name="First term",
        starts_at=datetime(2026, 6, 1, 9, 0),
        ends_at=None,
        registered=False,
        capacity_used=10,
        capacity_total=20,
        registration_opens_at=datetime(2026, 5, 20, 9, 0),
        registration_closes_at=datetime(2026, 5, 31, 23, 59),
        can_register=True,
        earned_points=44,
        max_points=51,
        registration_info="přihlásit",
        detail_url="https://www.vut.cz/studis/student.phtml?sn=termin_detail&tid=1",
    )

    dashboard = AssessmentDashboard(
        generated_at=NOW,
        horizon_days=30,
        include_past=False,
        items=[item],
        course_truncated_count=1,
        term_truncated_count=2,
        unavailable_course_codes=["DEF"],
    )

    assert dashboard.items[0].assessment_category == "zkouška"
    assert dashboard.items[0].can_register is True
    assert dashboard.items[0].detail_url.endswith("tid=1")
    assert dashboard.course_truncated_count == 1
    assert dashboard.term_truncated_count == 2
    assert dashboard.unavailable_course_codes == ["DEF"]


def test_build_assessment_dashboard_filters_and_sorts_terms() -> None:
    dashboard = build_assessment_dashboard(
        [
            _course_terms(
                "ABC",
                CourseTerm(
                    assessment_name="Exam",
                    name="Other",
                    starts_at=datetime(2026, 5, 27, 9, 0),
                    registered=False,
                    capacity_used=1,
                    capacity_total=20,
                    can_register=False,
                ),
                CourseTerm(
                    assessment_name="Exam",
                    name="Open later",
                    starts_at=datetime(2026, 5, 26, 9, 0),
                    registered=False,
                    can_register=True,
                ),
                CourseTerm(
                    assessment_name="Exam",
                    name="Registered later",
                    starts_at=datetime(2026, 5, 28, 9, 0),
                    registered=True,
                ),
                CourseTerm(
                    assessment_name="Exam",
                    name="Registered sooner",
                    starts_at=datetime(2026, 5, 25, 9, 0),
                    registered=True,
                ),
                CourseTerm(
                    assessment_name="Exam",
                    name="Completed",
                    starts_at=datetime(2026, 5, 20, 9, 0),
                    registered=True,
                ),
                CourseTerm(assessment_name="Credit", name="Undated"),
            )
        ],
        now=NOW,
        horizon_days=7,
        include_past=False,
    )

    assert [item.name for item in dashboard.items] == [
        "Registered sooner",
        "Registered later",
        "Open later",
        "Other",
        "Undated",
    ]
    assert dashboard.items[3].can_register is False
    assert dashboard.items[3].capacity_total == 20


def test_build_assessment_dashboard_can_include_past_but_respects_future_horizon() -> None:
    dashboard = build_assessment_dashboard(
        [
            _course_terms(
                "ABC",
                CourseTerm(name="Past", starts_at=datetime(2026, 5, 20, 9, 0)),
                CourseTerm(name="Soon", starts_at=datetime(2026, 5, 25, 9, 0)),
                CourseTerm(name="Later", starts_at=datetime(2026, 6, 25, 9, 0)),
            )
        ],
        now=NOW,
        horizon_days=7,
        include_past=True,
    )

    assert [item.name for item in dashboard.items] == ["Past", "Soon"]


def test_build_assessment_dashboard_reports_course_and_term_limits() -> None:
    course_limited = build_assessment_dashboard(
        [
            _course_terms(
                f"C{index:03}",
                CourseTerm(name=f"Term {index}", starts_at=datetime(2026, 6, 1, 9, 0)),
            )
            for index in range(101)
        ],
        now=NOW,
        horizon_days=30,
        include_past=False,
    )

    term_limited = build_assessment_dashboard(
        [
            _course_terms(
                "ABC",
                *[
                    CourseTerm(name=f"Term {index}", starts_at=datetime(2026, 6, 1, 9, 0))
                    for index in range(501)
                ],
            )
        ],
        now=NOW,
        horizon_days=30,
        include_past=False,
    )

    assert len(course_limited.items) == 100
    assert course_limited.course_truncated_count == 1
    assert course_limited.term_truncated_count == 0
    assert len(term_limited.items) == 500
    assert term_limited.course_truncated_count == 0
    assert term_limited.term_truncated_count == 1
