from vut_studis.client import _course_codes_from_grades, _course_from_grade
from vut_studis.models import (
    CompletionType,
    CourseLanguage,
    CourseType,
    Grade,
)


def test_course_codes_from_grades_deduplicates_in_order() -> None:
    codes = _course_codes_from_grades(
        [
            Grade(course_code="ABC", course_name="First"),
            Grade(course_code="DEF", course_name="Second"),
            Grade(course_code="abc", course_name="Duplicate"),
            Grade(course_code=None, course_name="No code"),
        ]
    )

    assert codes == ["ABC", "DEF"]


def test_course_from_grade_keeps_course_metadata() -> None:
    course = _course_from_grade(
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
