from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class StudisModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Course(StudisModel):
    code: str
    name: str
    semester: str | None = None
    completion: str | None = None


class ScheduleItem(StudisModel):
    course_code: str | None = None
    course_name: str
    starts_at: datetime
    ends_at: datetime
    room: str | None = None
    teacher: str | None = None
    kind: str | None = None


class ExamTerm(StudisModel):
    course_code: str | None = None
    course_name: str
    starts_at: datetime
    room: str | None = None
    registered: bool | None = None


class CourseLanguage(StrEnum):
    CZECH = "cs"
    ENGLISH = "en"


class CourseType(StrEnum):
    REQUIRED = "P"
    ELECTIVE = "V"


class CompletionType(StrEnum):
    CREDIT = "zá"
    EXAM = "zk"
    CREDIT_AND_EXAM = "zá,zk"
    CLASSIFIED_CREDIT = "kl"
    RECOGNIZED_EXAM = "uzk"
    RECOGNIZED_CLASSIFIED_CREDIT = "ukl"


class GradeValue(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"


class Grade(StudisModel):
    course_code: str | None = None
    course_name: str
    grade: GradeValue | None = None
    grade_awarded_on: date | None = None
    academic_year: str | None = None
    semester: str | None = None
    language: CourseLanguage | None = None
    course_type: CourseType | None = None
    credits: float | None = None
    in_study_plan: bool | None = None
    completion: CompletionType | None = None
    elearning: bool | None = None
    credit_awarded: bool | None = None
    credit_awarded_on: date | None = None
    points: float | None = None
    exam_term: int | None = None
    absolved: bool | None = None


class StudentSummary(StudisModel):
    courses_count: int
    upcoming_classes: list[ScheduleItem]
    upcoming_exams: list[ExamTerm]
    latest_grades: list[Grade]
