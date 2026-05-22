from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


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


class AssessmentEntry(StudisModel):
    name: str
    order: int | None = None
    points: float | None = None
    total_evaluation: bool | None = None
    fulfilled: bool | None = None
    reported: bool | None = None
    awarded_on: date | None = None
    evaluated_by: str | None = None
    message_url: str | None = None


class AssessmentItem(StudisModel):
    order: int | None = None
    name: str
    category: str | None = None
    min_points: float | None = None
    min_points_for_admission: float | None = None
    max_points: float | None = None
    points: float | None = None
    required: bool | None = None
    total_evaluation: bool | None = None
    fulfilled: bool | None = None
    reported: bool | None = None
    awarded_on: date | None = None
    evaluated_by: str | None = None
    message_url: str | None = None
    notes: list[str] = Field(default_factory=list)
    entries: list[AssessmentEntry] = Field(default_factory=list)


class CourseAssessment(StudisModel):
    course_code: str
    course_name: str | None = None
    academic_year: str | None = None
    credits: float | None = None
    completion: CompletionType | None = None
    items: list[AssessmentItem]


class CourseTerm(StudisModel):
    assessment_order: int | None = None
    assessment_name: str | None = None
    assessment_category: str | None = None
    term_number: int | None = None
    name: str
    note: str | None = None
    starts_at: datetime | None = None
    examiner: str | None = None
    room: str | None = None
    registered: bool | None = None
    capacity_used: int | None = None
    capacity_total: int | None = None
    registration_info: str | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    can_register: bool | None = None
    can_unregister: bool | None = None
    max_points: float | None = None
    earned_points: float | None = None
    detail_url: str | None = None


class CourseTerms(StudisModel):
    course_code: str
    course_name: str | None = None
    academic_year: str | None = None
    terms: list[CourseTerm]


class StudentSummary(StudisModel):
    courses_count: int
    upcoming_classes: list[ScheduleItem]
    upcoming_exams: list[ExamTerm]
    latest_grades: list[Grade]
