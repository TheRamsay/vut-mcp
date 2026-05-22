from datetime import date, datetime

from vut_studis.errors import StudisParseError
from vut_studis.models import (
    AssessmentEntry,
    AssessmentItem,
    Course,
    CourseAssessment,
    CourseAssignments,
    CourseTerms,
    Grade,
    PendingAction,
    PendingActionKind,
    PendingActionSeverity,
    PendingActionType,
    StudentSummary,
)


def course_codes_from_grades(grades: list[Grade]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for grade in grades:
        if grade.course_code is None:
            continue
        normalized = grade.course_code.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        codes.append(grade.course_code)
    return codes


def courses_from_grades(grades: list[Grade]) -> list[Course]:
    courses: list[Course] = []
    seen: set[str] = set()

    for grade in grades:
        if grade.course_code is None:
            continue

        normalized = grade.course_code.casefold()
        if normalized in seen:
            continue

        seen.add(normalized)
        courses.append(course_from_grade(grade))

    return courses


def course_from_grade(grade: Grade) -> Course:
    return Course(
        code=grade.course_code or "",
        name=grade.course_name,
        academic_year=grade.academic_year,
        semester=grade.semester,
        language=grade.language,
        course_type=grade.course_type,
        credits=grade.credits,
        in_study_plan=grade.in_study_plan,
        completion=grade.completion,
        elearning=grade.elearning,
        absolved=grade.absolved,
    )


def pending_actions_from_terms(terms: CourseTerms, *, now: datetime) -> list[PendingAction]:
    actions: list[PendingAction] = []
    for term in terms.terms:
        if term.starts_at is not None and term.starts_at < now:
            continue

        base = {
            "course_code": terms.course_code,
            "course_name": terms.course_name,
            "starts_at": term.starts_at,
            "registration_opens_at": term.registration_opens_at,
            "registration_closes_at": term.registration_closes_at,
            "registered": term.registered,
            "points": term.earned_points,
            "max_points": term.max_points,
            "detail_url": term.detail_url,
        }
        title = f"{term.assessment_name or 'Termín'}: {term.name}"

        if term.registered is True:
            actions.append(
                PendingAction(
                    type=PendingActionType.UPCOMING_REGISTERED_TERM,
                    severity=PendingActionSeverity.INFO,
                    action_kind=PendingActionKind.ATTEND,
                    title=title,
                    reason="You are registered for an upcoming assessment term.",
                    suggested_next_step="Keep the term in mind and prepare for it.",
                    days_left=_days_until(term.starts_at, now),
                    detail=term.registration_info,
                    due_at=term.starts_at,
                    **base,
                )
            )
            continue

        if term.can_register is True:
            actions.append(
                PendingAction(
                    type=PendingActionType.OPEN_TERM_REGISTRATION,
                    severity=_deadline_severity(term.registration_closes_at or term.starts_at, now),
                    action_kind=PendingActionKind.REGISTER,
                    title=title,
                    reason="Registration is currently open and you are not registered.",
                    suggested_next_step="Register for the term if you plan to attend it.",
                    days_left=_days_until(term.registration_closes_at or term.starts_at, now),
                    detail=term.registration_info,
                    due_at=term.registration_closes_at or term.starts_at,
                    **base,
                )
            )
            continue

        if term.registered is False:
            actions.append(
                PendingAction(
                    type=PendingActionType.UNREGISTERED_TERM,
                    severity=_deadline_severity(term.starts_at, now),
                    action_kind=PendingActionKind.REGISTER,
                    title=title,
                    reason="There is an upcoming term where you are not registered.",
                    suggested_next_step=(
                        "Check whether registration is available or choose another term."
                    ),
                    days_left=_days_until(term.starts_at, now),
                    detail=term.registration_info,
                    due_at=term.starts_at,
                    **base,
                )
            )

    return actions


def pending_actions_from_assignments(
    assignments: CourseAssignments,
    *,
    now: datetime,
) -> list[PendingAction]:
    actions: list[PendingAction] = []
    for assignment in assignments.assignments:
        base = {
            "course_code": assignments.course_code,
            "course_name": assignments.course_name,
            "registration_opens_at": assignment.registration_opens_at,
            "registration_closes_at": assignment.registration_closes_at,
            "registered": assignment.registered,
            "submitted": assignment.submitted,
            "detail_url": assignment.detail_url,
        }
        title = f"{assignment.assessment_name or 'Zadání'}: {assignment.name}"

        if assignment.can_register is True and assignment.registered is not True:
            actions.append(
                PendingAction(
                    type=PendingActionType.OPEN_ASSIGNMENT_REGISTRATION,
                    severity=_deadline_severity(assignment.registration_closes_at, now),
                    action_kind=PendingActionKind.REGISTER,
                    title=title,
                    reason="Assignment registration is open and you are not registered.",
                    suggested_next_step="Register for the assignment before registration closes.",
                    days_left=_days_until(assignment.registration_closes_at, now),
                    detail=assignment.registration_info,
                    due_at=assignment.registration_closes_at,
                    **base,
                )
            )

        if (
            assignment.submit_until is not None
            and assignment.submit_until >= now
            and assignment.submitted is not True
        ):
            actions.append(
                PendingAction(
                    type=PendingActionType.ASSIGNMENT_DEADLINE,
                    severity=_deadline_severity(assignment.submit_until, now),
                    action_kind=PendingActionKind.SUBMIT,
                    title=title,
                    reason="Assignment deadline is upcoming and no submission is recorded.",
                    suggested_next_step="Prepare and submit the assignment before the deadline.",
                    days_left=_days_until(assignment.submit_until, now),
                    detail=assignment.description,
                    due_at=assignment.submit_until,
                    **base,
                )
            )

    return actions


def pending_actions_from_assessment(assessment: CourseAssessment) -> list[PendingAction]:
    actions: list[PendingAction] = []
    for item in assessment.items:
        if item.min_points is None:
            continue

        has_unmet_points = item.points is not None and item.points < item.min_points
        marked_unfulfilled = item.fulfilled is False
        if not has_unmet_points and not marked_unfulfilled:
            continue

        actions.append(
            PendingAction(
                type=PendingActionType.UNMET_MINIMUM,
                severity=PendingActionSeverity.CRITICAL,
                action_kind=PendingActionKind.CHECK_POINTS,
                course_code=assessment.course_code,
                course_name=assessment.course_name,
                title=item.name,
                reason="The current points are below the required minimum.",
                suggested_next_step="Check remaining assessment opportunities for this course.",
                detail=item.category,
                points=item.points,
                min_points=item.min_points,
                max_points=item.max_points,
                detail_url=item.message_url,
            )
        )

    return actions


def pending_action_sort_key(action: PendingAction) -> tuple[int, datetime, str, str]:
    severity_priority = {
        PendingActionSeverity.CRITICAL: 0,
        PendingActionSeverity.WARNING: 1,
        PendingActionSeverity.INFO: 2,
    }[action.severity]
    type_priority = {
        PendingActionType.OPEN_TERM_REGISTRATION: 0,
        PendingActionType.OPEN_ASSIGNMENT_REGISTRATION: 0,
        PendingActionType.ASSIGNMENT_DEADLINE: 1,
        PendingActionType.UNREGISTERED_TERM: 2,
        PendingActionType.UPCOMING_REGISTERED_TERM: 3,
        PendingActionType.UNMET_MINIMUM: 4,
    }[action.type]
    when = action.due_at or action.starts_at or datetime.max
    return severity_priority, type_priority, when, action.course_code, action.title


def filter_pending_actions_by_horizon(
    actions: list[PendingAction],
    *,
    now: datetime,
    horizon_days: int | None,
) -> list[PendingAction]:
    if horizon_days is None:
        return actions

    horizon = now.date().toordinal() + horizon_days
    filtered: list[PendingAction] = []
    for action in actions:
        relevant_at = action.due_at or action.starts_at
        if relevant_at is None:
            filtered.append(action)
            continue
        if relevant_at.date().toordinal() <= horizon:
            filtered.append(action)
    return filtered


def _deadline_severity(deadline: datetime | None, now: datetime) -> PendingActionSeverity:
    days_left = _days_until(deadline, now)
    if days_left is None:
        return PendingActionSeverity.WARNING
    if days_left <= 2:
        return PendingActionSeverity.CRITICAL
    if days_left <= 7:
        return PendingActionSeverity.WARNING
    return PendingActionSeverity.INFO


def _days_until(deadline: datetime | None, now: datetime) -> int | None:
    if deadline is None:
        return None
    return (deadline.date() - now.date()).days


def find_assessment_message_target(
    assessment: CourseAssessment,
    item_order: int,
    entry_order: int | None,
) -> tuple[AssessmentItem, AssessmentEntry | None, str]:
    item = next((item for item in assessment.items if item.order == item_order), None)
    if item is None:
        raise StudisParseError(
            f"Assessment item {item_order!r} was not found for course {assessment.course_code!r}."
        )

    if entry_order is not None:
        entry = next((entry for entry in item.entries if entry.order == entry_order), None)
        if entry is None:
            raise StudisParseError(
                f"Assessment entry {entry_order!r} was not found for item {item_order!r}."
            )
        if entry.message_url is None:
            raise StudisParseError(
                f"Assessment entry {entry_order!r} does not have a message link."
            )
        return item, entry, entry.message_url

    if item.message_url is not None:
        return item, None, item.message_url

    entries_with_messages = [entry for entry in item.entries if entry.message_url is not None]
    if len(entries_with_messages) == 1:
        entry = entries_with_messages[0]
        return item, entry, entry.message_url or ""

    if entries_with_messages:
        raise StudisParseError(
            f"Assessment item {item_order!r} has multiple entry messages. Provide entry_order."
        )

    raise StudisParseError(f"Assessment item {item_order!r} does not have a message link.")


def build_student_summary(
    *,
    courses: list[Course],
    grades: list[Grade],
    pending_actions: list[PendingAction],
) -> StudentSummary:
    completed_courses = [course for course in courses if course.absolved is True]
    active_courses = [course for course in courses if course.absolved is not True]

    return StudentSummary(
        courses_count=len(courses),
        active_courses_count=len(active_courses),
        completed_courses_count=len(completed_courses),
        total_credits=sum_credits(courses),
        completed_credits=sum_credits(completed_courses),
        pending_actions_count=len(pending_actions),
        courses=courses,
        pending_actions=pending_actions[:20],
        latest_grades=latest_grades(grades, limit=10),
    )


def sum_credits(courses: list[Course]) -> float | None:
    credits = [course.credits for course in courses if course.credits is not None]
    if not credits:
        return None
    return sum(credits)


def latest_grades(grades: list[Grade], *, limit: int) -> list[Grade]:
    dated_grades = [
        grade
        for grade in grades
        if grade.grade_awarded_on is not None or grade.credit_awarded_on is not None
    ]
    return sorted(
        dated_grades,
        key=lambda grade: grade.grade_awarded_on or grade.credit_awarded_on or date.min,
        reverse=True,
    )[:limit]
