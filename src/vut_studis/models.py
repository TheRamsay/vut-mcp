from datetime import date, datetime

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


class Grade(StudisModel):
    course_code: str | None = None
    course_name: str
    value: str | None = None
    awarded_on: date | None = None


class StudentSummary(StudisModel):
    courses_count: int
    upcoming_classes: list[ScheduleItem]
    upcoming_exams: list[ExamTerm]
    latest_grades: list[Grade]
