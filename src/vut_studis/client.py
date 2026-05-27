from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from hashlib import sha256

import httpx
from pydantic import BaseModel

from vut_studis.aggregates import (
    build_student_summary,
    course_codes_from_grades,
    courses_from_grades,
    filter_pending_actions_by_horizon,
    find_assessment_message_target,
    pending_action_sort_key,
    pending_actions_from_assessment,
    pending_actions_from_assignments,
    pending_actions_from_terms,
)
from vut_studis.auth import refresh_session_cookie
from vut_studis.cache import (
    CacheStore,
    decode_model,
    decode_model_list,
    encode_model,
    encode_model_list,
)
from vut_studis.change_detection import (
    ChangeResource,
    detect_and_record_changes,
    model_change_resource,
)
from vut_studis.config import ENV_PATH, Settings, load_settings, set_env_value
from vut_studis.constants import (
    COURSE_DETAIL_CACHE_TTL,
    ELECTRONIC_INDEX_PATH,
    GRADES_CACHE_TTL,
)
from vut_studis.errors import StudisAuthError
from vut_studis.models import (
    AssessmentEntry,
    AssessmentItem,
    AssessmentMessage,
    Course,
    CourseAssessment,
    CourseAssignments,
    CourseTerms,
    ExamTerm,
    Grade,
    PendingAction,
    RecentChanges,
    ScheduleItem,
    StudentSummary,
)
from vut_studis.parsers.assessments import (
    parse_assessment_message_html,
    parse_course_assessment_html,
)
from vut_studis.parsers.assignments import (
    parse_assignment_detail_html,
    parse_assignment_submission_html,
    parse_course_assignments_html,
)
from vut_studis.parsers.grades import parse_grades_html
from vut_studis.parsers.terms import parse_course_terms_html


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
        response = await self._get_response(path)
        return response.text

    async def _get_response(self, path: str) -> httpx.Response:
        await self._ensure_session_cookie()
        response = await self._request_authenticated(path)
        if response is not None:
            return response

        if not self._can_refresh_session():
            raise StudisAuthError(
                "Studis session expired. Run `uv run vut-studis-debug login-refresh-session`."
            )

        await self._refresh_session_cookie()
        response = await self._request_authenticated(path)
        if response is None:
            raise StudisAuthError(
                "Studis session refresh succeeded, but the retry was not authenticated."
            )

        return response

    async def _request_authenticated(self, path: str) -> httpx.Response | None:
        async with self._http_client() as client:
            response = await client.get(path)
            response.raise_for_status()
            try:
                self._ensure_authenticated(response)
            except StudisAuthError:
                return None

            return response

    def _ensure_authenticated(self, response: httpx.Response) -> None:
        title_start = response.text[:2000].lower()
        if "jednotné přihlášení vut" in title_start or "auth/common" in str(response.url):
            raise StudisAuthError(
                "Studis session expired. Run `uv run vut-studis-debug login-refresh-session`."
            )

    async def _ensure_session_cookie(self) -> None:
        if self.settings.session_cookie:
            return

        if not self._can_refresh_session():
            raise StudisAuthError(
                "VUT_SESSION_COOKIE is not configured and VUT_USERNAME/VUT_PASSWORD "
                "are not available for automatic login."
            )

        await self._refresh_session_cookie()

    def _can_refresh_session(self) -> bool:
        return bool(self.settings.username and self.settings.password)

    async def _refresh_session_cookie(self) -> None:
        session_cookie = await refresh_session_cookie(self.settings)
        set_env_value(ENV_PATH, "VUT_SESSION_COOKIE", session_cookie)
        self.settings.session_cookie = session_cookie

    async def get_courses(self, *, force_refresh: bool = False) -> list[Course]:
        grades = await self.get_grades(force_refresh=force_refresh)
        return courses_from_grades(grades)

    async def get_schedule(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ScheduleItem]:
        raise NotImplementedError("Studis schedule endpoint/parser is not implemented yet.")

    async def get_exams(self) -> list[ExamTerm]:
        raise NotImplementedError("Studis exams endpoint/parser is not implemented yet.")

    async def get_pending_actions(
        self,
        *,
        course_codes: list[str] | None = None,
        horizon_days: int | None = None,
        force_refresh: bool = False,
    ) -> list[PendingAction]:
        if course_codes is None:
            grades = await self.get_grades(force_refresh=force_refresh)
            codes = course_codes_from_grades(grades)
        else:
            codes = course_codes
        actions: list[PendingAction] = []
        now = datetime.now()

        for course_code in codes:
            terms = await self.get_course_terms(course_code, force_refresh=force_refresh)
            assignments = await self.get_course_assignments(
                course_code,
                force_refresh=force_refresh,
            )
            assessment = await self.get_course_assessment(course_code, force_refresh=force_refresh)
            actions.extend(pending_actions_from_terms(terms, now=now))
            actions.extend(pending_actions_from_assignments(assignments, now=now))
            actions.extend(pending_actions_from_assessment(assessment))

        actions = filter_pending_actions_by_horizon(
            actions,
            now=now,
            horizon_days=horizon_days,
        )
        return sorted(actions, key=pending_action_sort_key)

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

    async def get_assessment_message(
        self,
        course_code: str,
        item_order: int,
        entry_order: int | None = None,
        *,
        force_refresh: bool = False,
    ) -> AssessmentMessage:
        assessment = await self.get_course_assessment(
            course_code,
            force_refresh=force_refresh,
        )
        item, entry, message_url = find_assessment_message_target(
            assessment,
            item_order,
            entry_order,
        )
        url_hash = sha256(message_url.encode("utf-8")).hexdigest()[:16]

        result = await self.cache.get_or_fetch(
            key=self._cache_key(
                "assessment_message",
                course_code.casefold(),
                str(item_order),
                str(entry_order or ""),
                url_hash,
            ),
            resource_type="assessment_message",
            ttl=COURSE_DETAIL_CACHE_TTL,
            force_refresh=force_refresh,
            fetch=lambda: self._fetch_assessment_message_live(
                url=message_url,
                assessment=assessment,
                item=item,
                entry=entry,
            ),
            encode=encode_model,
            decode=lambda payload: decode_model(payload, AssessmentMessage),
        )
        return result.value

    async def _fetch_assessment_message_live(
        self,
        *,
        url: str,
        assessment: CourseAssessment,
        item: AssessmentItem,
        entry: AssessmentEntry | None,
    ) -> AssessmentMessage:
        response = await self._get_response(url)
        return parse_assessment_message_html(
            response.text,
            url=str(response.url),
            course_code=assessment.course_code,
            course_name=assessment.course_name,
            item_order=item.order,
            item_name=item.name,
            entry_order=entry.order if entry is not None else None,
            entry_name=entry.name if entry is not None else None,
        )

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

        for assignment in assignments.assignments:
            if assignment.detail_url is None:
                enriched.append(assignment)
                continue

            detail_response = await self._get_response(assignment.detail_url)
            detail = parse_assignment_detail_html(
                detail_response.text,
                base_url=str(detail_response.url),
            )

            submitted_files = []
            submission_url = detail.get("submission_url")
            if isinstance(submission_url, str):
                submission_response = await self._get_response(submission_url)
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
        return await self._get_response(detail_path)

    async def get_student_summary(self, *, force_refresh: bool = False) -> StudentSummary:
        grades = await self.get_grades(force_refresh=force_refresh)
        courses = courses_from_grades(grades)
        course_codes = [course.code for course in courses]
        pending_actions = await self.get_pending_actions(
            course_codes=course_codes,
            horizon_days=30,
            force_refresh=force_refresh,
        )

        return build_student_summary(
            courses=courses,
            grades=grades,
            pending_actions=pending_actions,
        )

    async def get_recent_changes(self, *, force_refresh: bool = True) -> RecentChanges:
        grades = await self.get_grades(force_refresh=force_refresh)
        courses = courses_from_grades(grades)
        pending_actions = await self.get_pending_actions(
            course_codes=[course.code for course in courses],
            horizon_days=30,
            force_refresh=force_refresh,
        )
        resources = [
            *_course_change_resources(courses),
            *_grade_change_resources(grades),
            *_pending_action_change_resources(pending_actions),
        ]
        return detect_and_record_changes(
            cache=self.cache,
            scope=self._cache_scope(),
            resources=resources,
            resource_types=["course", "grade", "pending_action"],
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


def _course_change_resources(courses: list[Course]) -> list[ChangeResource]:
    return [
        model_change_resource(
            resource_type="course",
            resource_id=course.code,
            title=f"{course.code} {course.name}",
            course_code=course.code,
            model=course,
        )
        for course in courses
    ]


def _grade_change_resources(grades: list[Grade]) -> list[ChangeResource]:
    resources: list[ChangeResource] = []
    for grade in grades:
        if grade.course_code is None:
            continue

        parts = [
            grade.academic_year or "",
            grade.semester or "",
            grade.course_code,
        ]
        resources.append(
            model_change_resource(
                resource_type="grade",
                resource_id=":".join(parts),
                title=f"{grade.course_code} {grade.course_name}",
                course_code=grade.course_code,
                model=grade,
            )
        )
    return resources


def _pending_action_change_resources(actions: list[PendingAction]) -> list[ChangeResource]:
    resources: list[ChangeResource] = []
    for action in actions:
        resource_id = ":".join(
            [
                action.type,
                action.course_code,
                action.title,
                action.due_at.isoformat() if action.due_at is not None else "",
                action.starts_at.isoformat() if action.starts_at is not None else "",
            ]
        )
        resources.append(
            model_change_resource(
                resource_type="pending_action",
                resource_id=resource_id,
                title=f"{action.course_code} {action.title}",
                course_code=action.course_code,
                model=action,
            )
        )
    return resources
