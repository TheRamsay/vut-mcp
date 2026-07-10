import asyncio
from datetime import datetime, timedelta

import pytest

from vut_studis.client import StudisClient
from vut_studis.config import Settings
from vut_studis.errors import StudisAuthError, StudisParseError
from vut_studis.models import Course, CourseTerm, CourseTerms


def _client() -> StudisClient:
    return StudisClient(
        Settings(
            VUT_BASE_URL="https://www.vut.cz",
            VUT_SESSION_COOKIE="session=value",
            VUT_CACHE_DISABLED=True,
        )
    )


@pytest.mark.asyncio
async def test_assessment_dashboard_caps_course_fan_out_at_100_and_eight_requests() -> None:
    client = _client()
    courses = [Course(code=f"C{index:03}", name=f"Course {index}") for index in range(101)]
    active_requests = 0
    max_active_requests = 0

    async def get_courses(*, force_refresh: bool) -> list[Course]:
        assert force_refresh is True
        return courses

    async def get_course_terms(course_code: str, *, force_refresh: bool) -> CourseTerms:
        nonlocal active_requests, max_active_requests
        assert force_refresh is True
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0.001)
        active_requests -= 1
        return CourseTerms(
            course_code=course_code,
            terms=[CourseTerm(name="Term", starts_at=datetime.now() + timedelta(days=1))],
        )

    client.get_courses = get_courses  # type: ignore[method-assign]
    client.get_course_terms = get_course_terms  # type: ignore[method-assign]

    dashboard = await client.get_assessment_dashboard(force_refresh=True)

    assert len(dashboard.items) == 100
    assert dashboard.course_truncated_count == 1
    assert dashboard.term_truncated_count == 0
    assert max_active_requests == 8


@pytest.mark.asyncio
async def test_assessment_dashboard_filters_terms_and_records_parser_failures() -> None:
    client = _client()
    now = datetime.now()

    async def get_courses(*, force_refresh: bool) -> list[Course]:
        return [
            Course(code="GOOD", name="Good course"),
            Course(code="BAD", name="Unavailable course"),
        ]

    async def get_course_terms(course_code: str, *, force_refresh: bool) -> CourseTerms:
        if course_code == "BAD":
            raise StudisParseError("unexpected term table")
        return CourseTerms(
            course_code=course_code,
            terms=[
                CourseTerm(name="Past", starts_at=now - timedelta(days=1)),
                CourseTerm(name="Soon", starts_at=now + timedelta(days=2)),
                CourseTerm(name="Later", starts_at=now + timedelta(days=31)),
            ],
        )

    client.get_courses = get_courses  # type: ignore[method-assign]
    client.get_course_terms = get_course_terms  # type: ignore[method-assign]

    dashboard = await client.get_assessment_dashboard(horizon_days=30)

    assert [item.name for item in dashboard.items] == ["Soon"]
    assert dashboard.unavailable_course_codes == ["BAD"]


@pytest.mark.asyncio
async def test_assessment_dashboard_propagates_auth_errors() -> None:
    client = _client()

    async def get_courses(*, force_refresh: bool) -> list[Course]:
        return [Course(code="ABC", name="Test course")]

    async def get_course_terms(course_code: str, *, force_refresh: bool) -> CourseTerms:
        raise StudisAuthError("expired session")

    client.get_courses = get_courses  # type: ignore[method-assign]
    client.get_course_terms = get_course_terms  # type: ignore[method-assign]

    with pytest.raises(StudisAuthError, match="expired session"):
        await client.get_assessment_dashboard()
