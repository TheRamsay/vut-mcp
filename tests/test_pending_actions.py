from datetime import datetime

from vut_studis.aggregates import (
    pending_actions_from_assessment,
    pending_actions_from_assignments,
    pending_actions_from_terms,
)
from vut_studis.models import (
    AssessmentItem,
    CourseAssessment,
    CourseAssignment,
    CourseAssignments,
    CourseTerm,
    CourseTerms,
    PendingActionType,
)


def test_pending_actions_from_terms_flags_open_and_unregistered_future_terms() -> None:
    actions = pending_actions_from_terms(
        CourseTerms(
            course_code="ABC",
            course_name="Test Course",
            terms=[
                CourseTerm(
                    assessment_name="Exam",
                    name="1. termín",
                    starts_at=datetime(2026, 6, 1, 9, 0),
                    registered=False,
                    can_register=True,
                    registration_closes_at=datetime(2026, 5, 31, 23, 59),
                ),
                CourseTerm(
                    assessment_name="Exam",
                    name="2. termín",
                    starts_at=datetime(2026, 6, 15, 9, 0),
                    registered=False,
                ),
                CourseTerm(
                    assessment_name="Credit",
                    name="Zápočet",
                    starts_at=datetime(2026, 5, 10, 9, 0),
                    registered=False,
                    can_register=True,
                ),
            ],
        ),
        now=datetime(2026, 5, 22, 12, 0),
    )

    assert [action.type for action in actions] == [
        PendingActionType.OPEN_TERM_REGISTRATION,
        PendingActionType.UNREGISTERED_TERM,
    ]
    assert actions[0].course_code == "ABC"
    assert actions[0].due_at == datetime(2026, 5, 31, 23, 59)


def test_pending_actions_from_assignments_flags_registration_and_deadline() -> None:
    actions = pending_actions_from_assignments(
        CourseAssignments(
            course_code="ABC",
            course_name="Test Course",
            assignments=[
                CourseAssignment(
                    assessment_name="Project",
                    name="Implementation",
                    registered=False,
                    can_register=True,
                    registration_closes_at=datetime(2026, 5, 25, 23, 59),
                    submit_until=datetime(2026, 6, 1, 23, 59),
                    submitted=False,
                ),
                CourseAssignment(
                    assessment_name="Lab",
                    name="Submitted task",
                    submit_until=datetime(2026, 6, 2, 23, 59),
                    submitted=True,
                ),
            ],
        ),
        now=datetime(2026, 5, 22, 12, 0),
    )

    assert [action.type for action in actions] == [
        PendingActionType.OPEN_ASSIGNMENT_REGISTRATION,
        PendingActionType.ASSIGNMENT_DEADLINE,
    ]
    assert actions[1].submitted is False
    assert actions[1].due_at == datetime(2026, 6, 1, 23, 59)


def test_pending_actions_from_assessment_flags_unmet_minimum() -> None:
    actions = pending_actions_from_assessment(
        CourseAssessment(
            course_code="ABC",
            course_name="Test Course",
            items=[
                AssessmentItem(
                    name="Project",
                    category="projekty",
                    min_points=10,
                    max_points=20,
                    points=8,
                ),
                AssessmentItem(
                    name="Exam",
                    min_points=20,
                    points=25,
                ),
            ],
        )
    )

    assert len(actions) == 1
    assert actions[0].type == PendingActionType.UNMET_MINIMUM
    assert actions[0].title == "Project"
    assert actions[0].points == 8
    assert actions[0].min_points == 10
