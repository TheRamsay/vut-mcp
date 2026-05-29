from datetime import date, datetime

from vut_studis.aggregates import (
    build_course_status,
    build_student_summary,
    course_codes_from_grades,
    course_from_grade,
)
from vut_studis.models import (
    AssessmentItem,
    CompletionType,
    Course,
    CourseAssessment,
    CourseAssignments,
    CourseLanguage,
    CourseNote,
    CourseTerm,
    CourseTerms,
    CourseType,
    Grade,
    GradeValue,
    PendingAction,
    PendingActionKind,
    PendingActionSeverity,
    PendingActionType,
)


def test_course_codes_from_grades_deduplicates_in_order() -> None:
    codes = course_codes_from_grades(
        [
            Grade(course_code="ABC", course_name="First"),
            Grade(course_code="DEF", course_name="Second"),
            Grade(course_code="abc", course_name="Duplicate"),
            Grade(course_code=None, course_name="No code"),
        ]
    )

    assert codes == ["ABC", "DEF"]


def test_course_from_grade_keeps_course_metadata() -> None:
    course = course_from_grade(
        Grade(
            course_code="ABC",
            course_name="Test Course",
            academic_year="2025/2026",
            semester="Letní semestr, 1. ročník",
            language=CourseLanguage.CZECH,
            course_type=CourseType.REQUIRED,
            credits=5,
            in_study_plan=True,
            completion=CompletionType.EXAM,
            elearning=True,
            absolved=False,
        )
    )

    assert course.code == "ABC"
    assert course.name == "Test Course"
    assert course.academic_year == "2025/2026"
    assert course.semester == "Letní semestr, 1. ročník"
    assert course.language == CourseLanguage.CZECH
    assert course.course_type == CourseType.REQUIRED
    assert course.credits == 5
    assert course.in_study_plan is True
    assert course.completion == CompletionType.EXAM
    assert course.elearning is True
    assert course.absolved is False


def test_build_student_summary_counts_courses_and_latest_grades() -> None:
    summary = build_student_summary(
        courses=[
            Course(code="ABC", name="Active", credits=5, absolved=False),
            Course(code="DEF", name="Done", credits=4, absolved=True),
        ],
        grades=[
            Grade(course_code="ABC", course_name="Active", credit_awarded_on=date(2026, 5, 1)),
            Grade(course_code="DEF", course_name="Done", grade_awarded_on=date(2026, 5, 20)),
        ],
        pending_actions=[
            PendingAction(
                type=PendingActionType.ASSIGNMENT_DEADLINE,
                severity=PendingActionSeverity.WARNING,
                action_kind=PendingActionKind.SUBMIT,
                course_code="ABC",
                title="Project",
                reason="Deadline is upcoming.",
                suggested_next_step="Submit the assignment.",
            )
        ],
    )

    assert summary.courses_count == 2
    assert summary.active_courses_count == 1
    assert summary.completed_courses_count == 1
    assert summary.total_credits == 9
    assert summary.completed_credits == 4
    assert summary.pending_actions_count == 1
    assert summary.latest_grades[0].course_code == "DEF"
    assert summary.upcoming_classes == []
    assert summary.upcoming_exams == []


def test_build_course_status_groups_course_context() -> None:
    generated_at = datetime(2026, 5, 29, 9, 0)
    action = PendingAction(
        type=PendingActionType.UNMET_MINIMUM,
        severity=PendingActionSeverity.CRITICAL,
        action_kind=PendingActionKind.CHECK_POINTS,
        course_code="ABC",
        title="Project",
        reason="Minimum is not met.",
        suggested_next_step="Check remaining assessment opportunities.",
    )

    status = build_course_status(
        course_code="ABC",
        course=Course(code="ABC", name="Test Course", absolved=False),
        grades=[
            Grade(
                course_code="ABC",
                course_name="Test Course",
                points=12,
                grade=GradeValue.C,
                credit_awarded=False,
            )
        ],
        assessment=CourseAssessment(
            course_code="ABC",
            course_name="Test Course",
            items=[AssessmentItem(name="Project", min_points=15, points=12)],
        ),
        terms=CourseTerms(
            course_code="ABC",
            course_name="Test Course",
            terms=[CourseTerm(name="1. termín")],
        ),
        assignments=CourseAssignments(
            course_code="ABC",
            course_name="Test Course",
            assignments=[],
        ),
        pending_actions=[action],
        course_notes=[
            CourseNote(
                id="note-1",
                course_code="ABC",
                body="Ask about project repair.",
                created_at=generated_at,
                updated_at=generated_at,
            )
        ],
        generated_at=generated_at,
    )

    assert status.course_code == "ABC"
    assert status.course_name == "Test Course"
    assert status.pending_actions_count == 1
    assert status.critical_count == 1
    assert status.warning_count == 0
    assert status.summary == [
        "ABC: 12 points, grade C.",
        "Credit is not awarded yet.",
        "1 pending action(s); top priority: Project.",
        "1 local note(s) saved.",
    ]
