from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from hashlib import sha256

import httpx
from pydantic import BaseModel

from vut_studis.cache import (
    CacheStore,
    decode_model,
    decode_model_list,
    encode_model,
    encode_model_list,
)
from vut_studis.config import Settings, load_settings
from vut_studis.errors import StudisAuthError
from vut_studis.models import (
    Course,
    CourseAssessment,
    CourseAssignments,
    CourseTerms,
    ExamTerm,
    Grade,
    ScheduleItem,
    StudentSummary,
)
from vut_studis.parsers.assessments import parse_course_assessment_html
from vut_studis.parsers.assignments import (
    parse_assignment_detail_html,
    parse_assignment_submission_html,
    parse_course_assignments_html,
)
from vut_studis.parsers.grades import parse_grades_html
from vut_studis.parsers.terms import parse_course_terms_html

ELECTRONIC_INDEX_PATH = "/studis/student.phtml?sn=el_index"
GRADES_CACHE_TTL = timedelta(minutes=30)
COURSE_DETAIL_CACHE_TTL = timedelta(minutes=30)


class StudisClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        cache_store: CacheStore | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.cache = cache_store or CacheStore.from_settings(self.settings)

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

    async def get_grades(self, *, force_refresh: bool = False) -> list[Grade]:
        result = await self.cache.get_or_fetch(
            key=self._cache_key("grades"),
            resource_type="grades",
            ttl=GRADES_CACHE_TTL,
            force_refresh=force_refresh,
            fetch=self._fetch_grades_live,
            encode=encode_model_list,
            decode=lambda payload: decode_model_list(payload, Grade),
        )
        return result.value

    async def _fetch_grades_live(self) -> list[Grade]:
        html = await self._get_html(ELECTRONIC_INDEX_PATH)
        return parse_grades_html(html)

    async def get_course_grades(
        self,
        course_code: str,
        *,
        force_refresh: bool = False,
    ) -> list[Grade]:
        grades = await self.get_grades(force_refresh=force_refresh)
        normalized_code = course_code.casefold()
        return [
            grade
            for grade in grades
            if grade.course_code is not None and grade.course_code.casefold() == normalized_code
        ]

    async def get_course_assessment(
        self,
        course_code: str,
        *,
        force_refresh: bool = False,
    ) -> CourseAssessment:
        return await self._get_cached_course_detail(
            course_code=course_code,
            resource_type="course_assessment",
            ttl=COURSE_DETAIL_CACHE_TTL,
            force_refresh=force_refresh,
            fetch=lambda: self._fetch_course_assessment_live(course_code),
            model_type=CourseAssessment,
        )

    async def _fetch_course_assessment_live(self, course_code: str) -> CourseAssessment:
        response = await self._get_course_detail_response(course_code)
        return parse_course_assessment_html(response.text, base_url=str(response.url))

    async def get_course_terms(
        self,
        course_code: str,
        *,
        force_refresh: bool = False,
    ) -> CourseTerms:
        return await self._get_cached_course_detail(
            course_code=course_code,
            resource_type="course_terms",
            ttl=COURSE_DETAIL_CACHE_TTL,
            force_refresh=force_refresh,
            fetch=lambda: self._fetch_course_terms_live(course_code),
            model_type=CourseTerms,
        )

    async def _fetch_course_terms_live(self, course_code: str) -> CourseTerms:
        response = await self._get_course_detail_response(course_code)
        return parse_course_terms_html(response.text, base_url=str(response.url))

    async def get_course_assignments(
        self,
        course_code: str,
        *,
        force_refresh: bool = False,
    ) -> CourseAssignments:
        return await self._get_cached_course_detail(
            course_code=course_code,
            resource_type="course_assignments",
            ttl=COURSE_DETAIL_CACHE_TTL,
            force_refresh=force_refresh,
            fetch=lambda: self._fetch_course_assignments_live(course_code),
            model_type=CourseAssignments,
        )

    async def _fetch_course_assignments_live(self, course_code: str) -> CourseAssignments:
        response = await self._get_course_detail_response(course_code)
        assignments = parse_course_assignments_html(response.text, base_url=str(response.url))
        enriched = []

        async with self._http_client() as client:
            for assignment in assignments.assignments:
                if assignment.detail_url is None:
                    enriched.append(assignment)
                    continue

                detail_response = await client.get(assignment.detail_url)
                detail_response.raise_for_status()
                self._ensure_authenticated(detail_response)
                detail = parse_assignment_detail_html(
                    detail_response.text,
                    base_url=str(detail_response.url),
                )

                submitted_files = []
                submission_url = detail.get("submission_url")
                if isinstance(submission_url, str):
                    submission_response = await client.get(submission_url)
                    submission_response.raise_for_status()
                    self._ensure_authenticated(submission_response)
                    submitted_files = parse_assignment_submission_html(
                        submission_response.text,
                        base_url=str(submission_response.url),
                    )

                enriched.append(
                    assignment.model_copy(
                        update={
                            **detail,
                            "submitted": bool(submitted_files),
                            "submitted_files": submitted_files,
                        }
                    )
                )

        return assignments.model_copy(update={"assignments": enriched})

    async def _get_cached_course_detail[M: BaseModel](
        self,
        *,
        course_code: str,
        resource_type: str,
        ttl: timedelta,
        force_refresh: bool,
        fetch: Callable[[], Awaitable[M]],
        model_type: type[M],
    ) -> M:
        result = await self.cache.get_or_fetch(
            key=self._cache_key(resource_type, course_code.casefold()),
            resource_type=resource_type,
            ttl=ttl,
            force_refresh=force_refresh,
            fetch=fetch,
            encode=encode_model,
            decode=lambda payload: decode_model(payload, model_type),
        )
        return result.value

    async def _get_course_detail_response(self, course_code: str) -> httpx.Response:
        html = await self._get_html(ELECTRONIC_INDEX_PATH)
        detail_path = _find_course_detail_path(html, course_code)
        async with self._http_client() as client:
            response = await client.get(detail_path)
            response.raise_for_status()
            self._ensure_authenticated(response)
            return response

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

    def _cache_key(self, resource_type: str, *parts: str) -> str:
        key_parts = ["v1", self._cache_scope(), resource_type, *parts]
        return ":".join(key_parts)

    def _cache_scope(self) -> str:
        identity = self.settings.username or self.settings.session_cookie or "anonymous"
        raw_scope = f"{self.settings.base_url}|{identity}"
        return sha256(raw_scope.encode("utf-8")).hexdigest()[:16]


def _find_course_detail_path(html: str, course_code: str) -> str:
    from urllib.parse import urlparse

    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    normalized_code = course_code.casefold()
    for row in tree.css("tr"):
        cells = row.css("td")
        if len(cells) != 13:
            continue

        if cells[0].text(strip=True).casefold() != normalized_code:
            continue

        for link in row.css("a"):
            href = link.attributes.get("href") or ""
            if "sn=predmet_detail" in href:
                parsed = urlparse(href)
                path = parsed.path or "/studis/student.phtml"
                if path == "student.phtml":
                    path = f"/studis/{path}"
                return path + (f"?{parsed.query}" if parsed.query else "")

    raise StudisAuthError(f"Assessment detail link for course {course_code!r} was not found.")
