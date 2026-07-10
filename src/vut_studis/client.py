import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from urllib.parse import urljoin
from uuid import uuid4

import httpx
from pydantic import BaseModel

from vut_studis.aggregates import (
    MAX_ASSESSMENT_DASHBOARD_COURSES,
    build_assessment_dashboard,
    build_course_status,
    build_student_summary,
    course_codes_from_grades,
    course_from_grade,
    courses_from_grades,
    filter_pending_actions_by_horizon,
    find_assessment_message_target,
    pending_action_sort_key,
    pending_actions_from_assessment,
    pending_actions_from_assignments,
    pending_actions_from_terms,
)
from vut_studis.assistant import (
    briefing_item_id_for_action,
    briefing_item_id_for_change,
    build_daily_briefing,
)
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
from vut_studis.config import Settings, load_settings
from vut_studis.constants import (
    COURSE_DETAIL_CACHE_TTL,
    COURSE_UPDATES_CACHE_TTL,
    COURSE_UPDATES_PATH,
    ELECTRONIC_INDEX_PATH,
    GRADES_CACHE_TTL,
    PERSONAL_SCHEDULE_PATH,
    SCHEDULE_CACHE_TTL,
)
from vut_studis.errors import StudisAuthError, StudisParseError
from vut_studis.models import (
    AssessmentDashboard,
    AssessmentEntry,
    AssessmentItem,
    AssessmentMessage,
    ChangeNotificationResult,
    Course,
    CourseAssessment,
    CourseAssignments,
    CourseNote,
    CourseStatus,
    CourseStatusMode,
    CourseTerms,
    CourseUpdates,
    DailyBriefing,
    DismissedAction,
    ExamTerm,
    Grade,
    PendingAction,
    RecentChanges,
    ScheduleItem,
    StudentSummary,
)
from vut_studis.notifications import (
    NotificationMode,
    include_pending_actions_for_mode,
    plan_change_notifications,
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
from vut_studis.parsers.course_updates import parse_course_updates_html
from vut_studis.parsers.grades import parse_grades_html
from vut_studis.parsers.schedule import parse_schedule_html
from vut_studis.parsers.terms import parse_course_terms_html
from vut_studis.transport import StudisTransport


class StudisClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        cache_store: CacheStore | None = None,
        transport: StudisTransport | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.cache = cache_store or CacheStore.from_settings(self.settings)
        self.transport = transport or StudisTransport(self.settings)

    async def _get_html(self, path: str) -> str:
        return await self.transport.get_html(path)

    async def _get_response(self, path: str) -> httpx.Response:
        return await self.transport.get_response(path)

    async def get_courses(self, *, force_refresh: bool = False) -> list[Course]:
        grades = await self.get_grades(force_refresh=force_refresh)
        return courses_from_grades(grades)

    async def get_assessment_dashboard(
        self,
        *,
        horizon_days: int = 30,
        include_past: bool = False,
        force_refresh: bool = False,
    ) -> AssessmentDashboard:
        if (
            isinstance(horizon_days, bool)
            or not isinstance(horizon_days, int)
            or not 1 <= horizon_days <= 180
        ):
            raise ValueError("horizon_days must be between 1 and 180")
        if not isinstance(include_past, bool):
            raise ValueError("include_past must be a boolean")

        all_courses = await self.get_courses(force_refresh=force_refresh)
        courses = all_courses[:MAX_ASSESSMENT_DASHBOARD_COURSES]
        semaphore = asyncio.Semaphore(8)

        async def get_terms(course: Course) -> tuple[CourseTerms | None, str | None]:
            async with semaphore:
                try:
                    return (
                        await self.get_course_terms(
                            course.code,
                            force_refresh=force_refresh,
                        ),
                        None,
                    )
                except StudisParseError:
                    return None, course.code

        tasks = [asyncio.create_task(get_terms(course)) for course in courses]
        try:
            results = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        course_terms = [terms for terms, _ in results if terms is not None]
        unavailable_course_codes = [course_code for _, course_code in results if course_code]
        dashboard = build_assessment_dashboard(
            course_terms,
            now=datetime.now(),
            horizon_days=horizon_days,
            include_past=include_past,
        )
        return dashboard.model_copy(
            update={
                "course_truncated_count": max(len(all_courses) - len(courses), 0),
                "unavailable_course_codes": unavailable_course_codes,
            }
        )

    async def get_schedule(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ScheduleItem]:
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must not be after date_to")

        result = await self.cache.get_or_fetch(
            key=self._cache_key("schedule"),
            resource_type="schedule",
            ttl=SCHEDULE_CACHE_TTL,
            force_refresh=False,
            fetch=self._fetch_schedule_live,
            encode=encode_model_list,
            decode=lambda payload: decode_model_list(payload, ScheduleItem),
        )
        return _filter_schedule_by_date(result.value, date_from=date_from, date_to=date_to)

    async def _fetch_schedule_live(self) -> list[ScheduleItem]:
        html = await self._get_html(PERSONAL_SCHEDULE_PATH)
        return parse_schedule_html(html, base_url=str(self.settings.base_url))

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

    async def get_course_updates(
        self,
        limit: int = 100,
        *,
        force_refresh: bool = False,
    ) -> CourseUpdates:
        """Return bounded course-update metadata and links without fetching announcement bodies."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        result = await self.cache.get_or_fetch(
            key=self._cache_key("course_updates"),
            resource_type="course_updates",
            ttl=COURSE_UPDATES_CACHE_TTL,
            force_refresh=force_refresh,
            fetch=self._fetch_course_updates_live,
            encode=encode_model,
            decode=lambda payload: decode_model(payload, CourseUpdates),
        )
        updates = result.value
        omitted = max(0, len(updates.items) - limit)
        if omitted == 0:
            return updates
        return updates.model_copy(
            update={
                "items": updates.items[:limit],
                "truncated_count": omitted,
            }
        )

    async def _fetch_course_updates_live(self) -> CourseUpdates:
        html = await self._get_html(COURSE_UPDATES_PATH)
        return parse_course_updates_html(
            html,
            base_url=urljoin(str(self.settings.base_url), COURSE_UPDATES_PATH),
        )

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

    async def get_course_detail_urls(
        self,
        course_codes: list[str] | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, str]:
        if course_codes is None:
            grades = await self.get_grades(force_refresh=force_refresh)
            course_codes = course_codes_from_grades(grades)

        html = await self._get_html(ELECTRONIC_INDEX_PATH)
        detail_urls: dict[str, str] = {}
        for course_code in course_codes:
            try:
                detail_path = _find_course_detail_path(html, course_code)
            except StudisAuthError:
                continue
            detail_urls[course_code] = urljoin(str(self.settings.base_url), detail_path)

        return detail_urls

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

    async def get_course_status(
        self,
        course_code: str,
        *,
        mode: CourseStatusMode = CourseStatusMode.SUMMARY,
        horizon_days: int | None = 30,
        force_refresh: bool = False,
    ) -> CourseStatus:
        mode = CourseStatusMode(mode)
        grades = await self.get_course_grades(course_code, force_refresh=force_refresh)
        now = datetime.now()
        course = course_from_grade(grades[0]) if grades else None
        assessment = None
        terms = None
        assignments = None
        pending_actions: list[PendingAction] = []
        pending_actions_loaded = False

        if mode == CourseStatusMode.FULL:
            assessment = await self.get_course_assessment(course_code, force_refresh=force_refresh)
            terms = await self.get_course_terms(course_code, force_refresh=force_refresh)
            assignments = await self.get_course_assignments(
                course_code,
                force_refresh=force_refresh,
            )
            pending_actions = [
                *pending_actions_from_terms(terms, now=now),
                *pending_actions_from_assignments(assignments, now=now),
                *pending_actions_from_assessment(assessment),
            ]
            pending_actions = filter_pending_actions_by_horizon(
                pending_actions,
                now=now,
                horizon_days=horizon_days,
            )
            pending_actions_loaded = True

        return build_course_status(
            course_code=course_code,
            mode=mode,
            course=course,
            grades=grades,
            assessment=assessment,
            terms=terms,
            assignments=assignments,
            pending_actions=pending_actions,
            pending_actions_loaded=pending_actions_loaded,
            course_notes=self.get_course_notes(course_code),
            generated_at=now,
        )

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

    async def get_recent_changes(
        self,
        *,
        force_refresh: bool = True,
        include_pending_actions: bool = True,
    ) -> RecentChanges:
        grades = await self.get_grades(force_refresh=force_refresh)
        courses = courses_from_grades(grades)
        resources = [
            *_course_change_resources(courses),
            *_grade_change_resources(grades),
        ]
        resource_types = ["course", "grade"]

        if include_pending_actions:
            pending_actions = await self.get_pending_actions(
                course_codes=[course.code for course in courses],
                horizon_days=30,
                force_refresh=force_refresh,
            )
            resources.extend(_pending_action_change_resources(pending_actions))
            resource_types.append("pending_action")

        return detect_and_record_changes(
            cache=self.cache,
            scope=self._cache_scope(),
            resources=resources,
            resource_types=resource_types,
        )

    async def get_change_notifications(
        self,
        *,
        mode: NotificationMode = "fast",
        force_refresh: bool = True,
        private: bool = False,
        mark_delivered: bool = True,
    ) -> ChangeNotificationResult:
        changes = await self.get_recent_changes(
            force_refresh=force_refresh,
            include_pending_actions=include_pending_actions_for_mode(mode),
        )
        planned = plan_change_notifications(changes, private=private)
        delivered_ids = self.cache.get_delivered_notification_ids(
            scope=self._cache_scope(),
            notification_ids=[notification.id for notification in planned],
        )
        notifications = [
            notification for notification in planned if notification.id not in delivered_ids
        ]

        if mark_delivered:
            self.cache.record_delivered_notifications(
                scope=self._cache_scope(),
                notification_ids=[notification.id for notification in notifications],
            )

        return ChangeNotificationResult(
            baseline_created=changes.baseline_created,
            captured_at=changes.captured_at,
            notifications=notifications,
            suppressed_count=len(planned) - len(notifications),
        )

    def record_change_notifications_delivered(self, notification_ids: list[str]) -> None:
        self.cache.record_delivered_notifications(
            scope=self._cache_scope(),
            notification_ids=notification_ids,
        )

    async def get_daily_briefing(
        self,
        *,
        horizon_days: int = 7,
        force_refresh: bool = False,
        include_changes: bool = True,
    ) -> DailyBriefing:
        pending_actions = await self.get_pending_actions(
            horizon_days=horizon_days,
            force_refresh=force_refresh,
        )
        notifications = []
        if include_changes:
            changes = await self.get_change_notifications(
                mode="fast",
                force_refresh=force_refresh,
                mark_delivered=False,
            )
            notifications = changes.notifications
        action_ids = [
            *[briefing_item_id_for_action(action) for action in pending_actions],
            *[briefing_item_id_for_change(notification) for notification in notifications],
        ]
        dismissed_ids = self.cache.get_dismissed_action_ids(
            scope=self._cache_scope(),
            action_ids=action_ids,
        )

        return build_daily_briefing(
            pending_actions=pending_actions,
            change_notifications=notifications,
            course_notes=self.cache.list_course_notes(scope=self._cache_scope()),
            dismissed_action_ids=dismissed_ids,
            horizon_days=horizon_days,
        )

    def dismiss_briefing_item(
        self,
        action_id: str,
        *,
        reason: str | None = None,
    ) -> DismissedAction:
        dismissed = self.cache.dismiss_action(
            scope=self._cache_scope(),
            action_id=action_id,
            reason=reason,
        )
        return DismissedAction(
            action_id=dismissed.action_id,
            reason=dismissed.reason,
            dismissed_at=dismissed.dismissed_at,
        )

    def add_course_note(self, course_code: str, body: str) -> CourseNote:
        note = self.cache.add_course_note(
            scope=self._cache_scope(),
            note_id=uuid4().hex,
            course_code=course_code,
            body=body,
        )
        return CourseNote(
            id=note.note_id,
            course_code=note.course_code,
            body=note.body,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )

    def get_course_notes(self, course_code: str | None = None) -> list[CourseNote]:
        return [
            CourseNote(
                id=note.note_id,
                course_code=note.course_code,
                body=note.body,
                created_at=note.created_at,
                updated_at=note.updated_at,
            )
            for note in self.cache.list_course_notes(
                scope=self._cache_scope(),
                course_code=course_code,
            )
        ]

    def _cache_key(self, resource_type: str, *parts: str) -> str:
        key_parts = ["v1", self._cache_scope(), resource_type, *parts]
        return ":".join(key_parts)

    def _cache_scope(self) -> str:
        identity = self.settings.username or self.settings.session_cookie or "anonymous"
        raw_scope = f"{self.settings.base_url}|{identity}"
        return sha256(raw_scope.encode("utf-8")).hexdigest()[:16]


def _filter_schedule_by_date(
    items: list[ScheduleItem],
    *,
    date_from: date | None,
    date_to: date | None,
) -> list[ScheduleItem]:
    """Return items intersecting the requested inclusive local-date window."""
    window_start = datetime.combine(date_from, time.min) if date_from is not None else None
    window_end = (
        datetime.combine(date_to + timedelta(days=1), time.min)
        if date_to is not None and date_to < date.max
        else None
    )
    return [
        item
        for item in items
        if (window_start is None or item.ends_at > window_start)
        and (window_end is None or item.starts_at < window_end)
    ]


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
