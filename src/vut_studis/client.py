from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
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
from vut_studis.errors import StudisAuthError, StudisParseError
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
    PendingActionType,
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

    async def get_pending_actions(
        self,
        *,
        course_codes: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[PendingAction]:
        if course_codes is None:
            grades = await self.get_grades(force_refresh=force_refresh)
            codes = _course_codes_from_grades(grades)
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
            actions.extend(_pending_actions_from_terms(terms, now=now))
            actions.extend(_pending_actions_from_assignments(assignments, now=now))
            actions.extend(_pending_actions_from_assessment(assessment))

        return sorted(actions, key=_pending_action_sort_key)

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
        item, entry, message_url = _find_assessment_message_target(
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
        async with self._http_client() as client:
            response = await client.get(url)
            response.raise_for_status()
            self._ensure_authenticated(response)

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


def _course_codes_from_grades(grades: list[Grade]) -> list[str]:
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


def _find_assessment_message_target(
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


def _pending_actions_from_terms(terms: CourseTerms, *, now: datetime) -> list[PendingAction]:
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
                    title=title,
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
                    title=title,
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
                    title=title,
                    detail=term.registration_info,
                    due_at=term.starts_at,
                    **base,
                )
            )

    return actions


def _pending_actions_from_assignments(
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
                    title=title,
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
                    title=title,
                    detail=assignment.description,
                    due_at=assignment.submit_until,
                    **base,
                )
            )

    return actions


def _pending_actions_from_assessment(assessment: CourseAssessment) -> list[PendingAction]:
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
                course_code=assessment.course_code,
                course_name=assessment.course_name,
                title=item.name,
                detail=item.category,
                points=item.points,
                min_points=item.min_points,
                max_points=item.max_points,
                detail_url=item.message_url,
            )
        )

    return actions


def _pending_action_sort_key(action: PendingAction) -> tuple[int, datetime, str, str]:
    priority = {
        PendingActionType.OPEN_TERM_REGISTRATION: 0,
        PendingActionType.OPEN_ASSIGNMENT_REGISTRATION: 0,
        PendingActionType.ASSIGNMENT_DEADLINE: 1,
        PendingActionType.UNREGISTERED_TERM: 2,
        PendingActionType.UPCOMING_REGISTERED_TERM: 3,
        PendingActionType.UNMET_MINIMUM: 4,
    }[action.type]
    when = action.due_at or action.starts_at or datetime.max
    return priority, when, action.course_code, action.title
