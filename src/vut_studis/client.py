from datetime import date

import httpx

from vut_studis.config import Settings, load_settings
from vut_studis.errors import StudisAuthError
from vut_studis.models import Course, ExamTerm, Grade, ScheduleItem, StudentSummary
from vut_studis.parsers.grades import parse_grades_html

ELECTRONIC_INDEX_PATH = "/studis/student.phtml?sn=el_index"


class StudisClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def _headers(self) -> dict[str, str]:
        if not self.settings.session_cookie:
            raise StudisAuthError("VUT_SESSION_COOKIE is not configured.")

        return {"Cookie": self.settings.session_cookie}

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=str(self.settings.base_url),
            follow_redirects=True,
            timeout=self.settings.http_timeout_seconds,
            headers=self._headers(),
        )

    async def _get_html(self, path: str) -> str:
        async with self._http_client() as client:
            response = await client.get(path)
            response.raise_for_status()
            self._ensure_authenticated(response)
            return response.text

    def _ensure_authenticated(self, response: httpx.Response) -> None:
        title_start = response.text[:2000].lower()
        if "jednotné přihlášení vut" in title_start or "auth/common" in str(response.url):
            raise StudisAuthError(
                "Studis session expired. Run `uv run vut-studis-debug login-refresh-session`."
            )

    async def get_courses(self) -> list[Course]:
        raise NotImplementedError("Studis courses endpoint/parser is not implemented yet.")

    async def get_schedule(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ScheduleItem]:
        raise NotImplementedError("Studis schedule endpoint/parser is not implemented yet.")

    async def get_exams(self) -> list[ExamTerm]:
        raise NotImplementedError("Studis exams endpoint/parser is not implemented yet.")

    async def get_grades(self) -> list[Grade]:
        html = await self._get_html(ELECTRONIC_INDEX_PATH)
        return parse_grades_html(html)

    async def get_course_grades(self, course_code: str) -> list[Grade]:
        grades = await self.get_grades()
        normalized_code = course_code.casefold()
        return [
            grade
            for grade in grades
            if grade.course_code is not None and grade.course_code.casefold() == normalized_code
        ]

    async def get_student_summary(self) -> StudentSummary:
        courses = await self.get_courses()
        schedule = await self.get_schedule()
        exams = await self.get_exams()
        grades = await self.get_grades()

        return StudentSummary(
            courses_count=len(courses),
            upcoming_classes=schedule[:10],
            upcoming_exams=exams[:10],
            latest_grades=grades[:10],
        )
