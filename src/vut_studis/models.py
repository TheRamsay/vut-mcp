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


class PendingActionType(StrEnum):
    OPEN_TERM_REGISTRATION = "open_term_registration"
    UNREGISTERED_TERM = "unregistered_term"
    UPCOMING_REGISTERED_TERM = "upcoming_registered_term"
    OPEN_ASSIGNMENT_REGISTRATION = "open_assignment_registration"
    ASSIGNMENT_DEADLINE = "assignment_deadline"
    UNMET_MINIMUM = "unmet_minimum"


class PendingAction(StudisModel):
    type: PendingActionType
    course_code: str
    course_name: str | None = None
    title: str
    detail: str | None = None
    due_at: datetime | None = None
    starts_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    points: float | None = None
    min_points: float | None = None
    max_points: float | None = None
    registered: bool | None = None
    submitted: bool | None = None
    detail_url: str | None = None


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


class AssessmentMessage(StudisModel):
    course_code: str
    course_name: str | None = None
    item_order: int | None = None
    item_name: str | None = None
    entry_order: int | None = None
    entry_name: str | None = None
    title: str | None = None
    subject: str | None = None
    sender: str | None = None
    sent_at: datetime | None = None
    body: str
    url: str


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


class AssignmentSubmissionFile(StudisModel):
    name: str
    size: str | None = None
    uploaded_at: datetime | None = None
    uploaded_by: str | None = None
    download_url: str | None = None


class CourseAssignment(StudisModel):
    assessment_order: int | None = None
    assessment_name: str | None = None
    assessment_category: str | None = None
    assignment_number: int | None = None
    name: str
    teacher: str | None = None
    description: str | None = None
    submit_until: datetime | None = None
    registered: bool | None = None
    registered_at: datetime | None = None
    auto_registration: bool | None = None
    capacity_used: int | None = None
    capacity_total: int | None = None
    registration_info: str | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    unregistration_closes_at: datetime | None = None
    can_register: bool | None = None
    can_unregister: bool | None = None
    submitted: bool | None = None
    submitted_files: list[AssignmentSubmissionFile] = Field(default_factory=list)
    detail_url: str | None = None
    submission_url: str | None = None


class CourseAssignments(StudisModel):
    course_code: str
    course_name: str | None = None
    academic_year: str | None = None
    assignments: list[CourseAssignment]


class StudentSummary(StudisModel):
    courses_count: int
    upcoming_classes: list[ScheduleItem]
    upcoming_exams: list[ExamTerm]
    latest_grades: list[Grade]
