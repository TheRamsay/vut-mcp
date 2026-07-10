"""Read-only Moodle client with opt-in REST and authenticated web fallback."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urljoin, urlparse

from vut_moodle.api import MoodleApi
from vut_moodle.errors import MoodleApiError, MoodleConfigurationError, MoodleDataError
from vut_moodle.models import MoodleAssignment, MoodleCourse, MoodleFile
from vut_moodle.parsers import (
    parse_assignment_page,
    parse_course_assignments,
    parse_dashboard_courses,
)
from vut_moodle.transport import MoodleTransport
from vut_studis.cache import CacheStore, decode_model_list, encode_model_list
from vut_studis.config import Settings, load_settings

COURSES_TTL = timedelta(minutes=15)
ASSIGNMENTS_TTL = timedelta(minutes=5)
ASSIGNMENT_FILES_TTL = timedelta(minutes=60)
MAX_COURSES = 50
MAX_ASSIGNMENTS = 200


class MoodleClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        cache_store: CacheStore | None = None,
        transport: MoodleTransport | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.cache = cache_store or CacheStore.from_settings(self.settings)
        self.transport = transport or MoodleTransport(self.settings)

    async def get_courses(self, *, force_refresh: bool = False) -> list[MoodleCourse]:
        result = await self.cache.get_or_fetch(
            key=self._cache_key("moodle_courses"),
            resource_type="moodle_courses",
            ttl=COURSES_TTL,
            force_refresh=force_refresh,
            fetch=self._fetch_courses,
            encode=encode_model_list,
            decode=lambda payload: decode_model_list(payload, MoodleCourse),
        )
        return result.value

    async def get_assignments(
        self,
        course_id: int | None = None,
        *,
        force_refresh: bool = False,
    ) -> list[MoodleAssignment]:
        result = await self.cache.get_or_fetch(
            key=self._cache_key("moodle_assignments"),
            resource_type="moodle_assignments",
            ttl=ASSIGNMENTS_TTL,
            force_refresh=force_refresh,
            fetch=self._fetch_assignments,
            encode=encode_model_list,
            decode=lambda payload: decode_model_list(payload, MoodleAssignment),
        )
        assignments = result.value
        if course_id is None:
            return assignments
        return [assignment for assignment in assignments if assignment.course_id == course_id]

    async def get_assignment_files(
        self,
        assignment_id: int,
        *,
        force_refresh: bool = False,
    ) -> list[MoodleFile]:
        result = await self.cache.get_or_fetch(
            key=self._cache_key("moodle_assignment_files", str(assignment_id)),
            resource_type="moodle_assignment_files",
            ttl=ASSIGNMENT_FILES_TTL,
            force_refresh=force_refresh,
            fetch=lambda: self._fetch_assignment_files(assignment_id),
            encode=encode_model_list,
            decode=lambda payload: decode_model_list(payload, MoodleFile),
        )
        return result.value

    def _use_api(self) -> bool:
        return self.settings.moodle_access_mode == "api" or (
            self.settings.moodle_access_mode == "auto" and bool(self.settings.moodle_token)
        )

    async def _fetch_courses(self) -> list[MoodleCourse]:
        if not self._use_api():
            return await self._fetch_courses_web()
        try:
            return await self._fetch_courses_api()
        except MoodleApiError:
            if self.settings.moodle_access_mode == "api":
                raise
            return await self._fetch_courses_web()

    async def _fetch_assignments(self) -> list[MoodleAssignment]:
        if not self._use_api():
            return await self._fetch_assignments_web()
        try:
            return await self._fetch_assignments_api()
        except MoodleApiError:
            if self.settings.moodle_access_mode == "api":
                raise
            return await self._fetch_assignments_web()

    async def _fetch_assignment_files(self, assignment_id: int) -> list[MoodleFile]:
        assignments = await self.get_assignments()
        for assignment in assignments:
            if assignment.id == assignment_id:
                if not self._use_api():
                    return assignment.files
                try:
                    return await self._fetch_assignment_files_api(assignment)
                except MoodleApiError:
                    if self.settings.moodle_access_mode == "api":
                        raise
                    return assignment.files
        raise MoodleDataError(f"Moodle assignment {assignment_id} was not found.")

    async def _fetch_assignment_files_api(self, assignment: MoodleAssignment) -> list[MoodleFile]:
        sections = await self._api().get_course_contents(assignment.course_id)
        for section in sections:
            modules = section.get("modules")
            if not isinstance(modules, list):
                continue
            for module in modules:
                if not isinstance(module, dict):
                    continue
                if _positive_int(module.get("instance")) != assignment.id:
                    continue
                files = _files_from_api(module.get("contents"), self._moodle_url)
                return files or assignment.files
        return assignment.files

    async def _fetch_courses_api(self) -> list[MoodleCourse]:
        api = self._api()
        site_info = await api.get_site_info()
        user_id = _positive_int(site_info.get("userid"))
        if user_id is None:
            raise MoodleApiError(
                "core_webservice_get_site_info",
                "Moodle did not return a user ID.",
            )
        courses: list[MoodleCourse] = []
        for course in await api.get_user_courses(user_id):
            course_id = _positive_int(course.get("id"))
            name = _text(course.get("fullname"))
            if course_id is None or not name:
                continue
            courses.append(
                MoodleCourse(
                    id=course_id,
                    name=name,
                    short_name=_text(course.get("shortname")),
                    url=self._moodle_url(f"/course/view.php?id={course_id}"),
                )
            )
        return courses

    async def _fetch_assignments_api(self) -> list[MoodleAssignment]:
        courses = await self.get_courses()
        if len(courses) > MAX_COURSES:
            raise MoodleDataError(f"Moodle course limit of {MAX_COURSES} exceeded.")
        if not courses:
            return []
        course_by_id = {course.id: course for course in courses}
        payload = await self._api().get_assignments(list(course_by_id))
        assignments: list[MoodleAssignment] = []
        raw_courses = payload.get("courses")
        if not isinstance(raw_courses, list):
            raise MoodleApiError(
                "mod_assign_get_assignments",
                "Moodle returned no course assignments.",
            )
        for raw_course in raw_courses:
            if not isinstance(raw_course, dict):
                continue
            course_id = _positive_int(raw_course.get("id"))
            course = course_by_id.get(course_id) if course_id is not None else None
            raw_assignments = raw_course.get("assignments")
            if course is None or not isinstance(raw_assignments, list):
                continue
            for raw_assignment in raw_assignments:
                if not isinstance(raw_assignment, dict):
                    continue
                assignment = self._assignment_from_api(raw_assignment, course)
                if assignment is not None:
                    assignments.append(assignment)
                    if len(assignments) > MAX_ASSIGNMENTS:
                        raise MoodleDataError(
                            f"Moodle assignment limit of {MAX_ASSIGNMENTS} exceeded."
                        )
        return assignments

    async def _fetch_courses_web(self) -> list[MoodleCourse]:
        response = await self.transport.get_response("/my/")
        courses = parse_dashboard_courses(response.text, base_url=str(response.url))
        if len(courses) > MAX_COURSES:
            raise MoodleDataError(f"Moodle course limit of {MAX_COURSES} exceeded.")
        return courses

    async def _fetch_assignments_web(self) -> list[MoodleAssignment]:
        courses = await self.get_courses()
        if len(courses) > MAX_COURSES:
            raise MoodleDataError(f"Moodle course limit of {MAX_COURSES} exceeded.")
        assignments: list[MoodleAssignment] = []
        for course in courses:
            course_response = await self.transport.get_response(course.url)
            assignment_links = parse_course_assignments(
                course_response.text,
                base_url=str(course_response.url),
                course=course,
            )
            for _assignment_id, assignment_url in assignment_links:
                assignment_response = await self.transport.get_response(assignment_url)
                assignments.append(
                    parse_assignment_page(
                        assignment_response.text,
                        base_url=str(assignment_response.url),
                        course_id=course.id,
                        course_name=course.name,
                    )
                )
                if len(assignments) > MAX_ASSIGNMENTS:
                    raise MoodleDataError(f"Moodle assignment limit of {MAX_ASSIGNMENTS} exceeded.")
        return assignments

    def _api(self) -> MoodleApi:
        if not self.settings.moodle_token:
            raise MoodleConfigurationError(
                "VUT_MOODLE_TOKEN must be configured when VUT_MOODLE_ACCESS_MODE=api."
            )
        return MoodleApi(self.settings)

    def _assignment_from_api(
        self,
        payload: dict[object, object],
        course: MoodleCourse,
    ) -> MoodleAssignment | None:
        assignment_id = _positive_int(payload.get("id"))
        name = _text(payload.get("name"))
        if assignment_id is None or not name:
            return None
        return MoodleAssignment(
            id=assignment_id,
            course_id=course.id,
            course_name=course.name,
            name=name,
            url=self._moodle_url(f"/mod/assign/view.php?id={assignment_id}"),
            due_at=_unix_datetime(payload.get("duedate")),
            cutoff_at=_unix_datetime(payload.get("cutoffdate")),
            submission_status=_submission_status(payload.get("submissionstatus")),
            files=_files_from_api(payload.get("introattachments"), self._moodle_url),
        )

    def _moodle_url(self, url: str) -> str:
        absolute = urljoin(str(self.settings.moodle_base_url), url)
        if _origin(absolute) != _origin(str(self.settings.moodle_base_url)):
            raise MoodleDataError("Moodle returned a URL outside the configured Moodle origin.")
        return absolute

    def _cache_key(self, resource_type: str, *parts: str) -> str:
        return ":".join(["v1", self._cache_scope(), self._normalized_mode(), resource_type, *parts])

    def _cache_scope(self) -> str:
        identity = self.settings.username or self.settings.moodle_session_cookie or "anonymous"
        raw_scope = f"{self.settings.moodle_base_url}|{identity}"
        return sha256(raw_scope.encode("utf-8")).hexdigest()[:16]

    def _normalized_mode(self) -> str:
        return "api" if self._use_api() else "web"


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _unix_datetime(value: object) -> datetime | None:
    timestamp = _positive_int(value)
    return datetime.fromtimestamp(timestamp, UTC) if timestamp is not None else None


def _submission_status(value: object) -> str:
    if value in {"new", "draft", "submitted"}:
        return str(value)
    return "unknown"


def _files_from_api(value: object, url: Callable[[str], str]) -> list[MoodleFile]:
    if not isinstance(value, list):
        return []
    files: list[MoodleFile] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("filename"))
        file_url = _text(item.get("fileurl"))
        if not name or not file_url:
            continue
        files.append(
            MoodleFile(
                name=name,
                url=url(file_url),
                size_bytes=_positive_int(item.get("filesize")),
                mimetype=_text(item.get("mimetype")),
                modified_at=_unix_datetime(item.get("timemodified")),
            )
        )
    return files


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise MoodleDataError("Moodle returned an invalid URL.") from error
    if not parsed.scheme or not parsed.hostname:
        raise MoodleDataError("Moodle returned an invalid URL.")
    return parsed.scheme.casefold(), parsed.hostname.casefold(), port or {
        "http": 80,
        "https": 443,
    }.get(parsed.scheme.casefold())
