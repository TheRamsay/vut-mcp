from datetime import date
from typing import cast

from fastmcp import FastMCP

from vut_mcp.context import get_studis_client
from vut_mcp.payloads import course_points_payload
from vut_studis.notifications import NotificationMode

mcp = FastMCP("VUT Studis")


@mcp.tool()
async def vut_get_schedule(date_from: date | None = None, date_to: date | None = None):
    """Get the student's VUT Studis schedule."""
    return await get_studis_client().get_schedule(date_from=date_from, date_to=date_to)


@mcp.tool()
async def vut_get_student_summary(force_refresh: bool = False):
    """Get a compact summary of the student's current Studis state."""
    return await get_studis_client().get_student_summary(force_refresh=force_refresh)


@mcp.tool()
async def vut_get_pending_actions(
    course_codes: list[str] | None = None,
    horizon_days: int | None = None,
    force_refresh: bool = False,
):
    """Get pending registrations, deadlines, upcoming terms, and unmet point minima."""
    return await get_studis_client().get_pending_actions(
        course_codes=course_codes,
        horizon_days=horizon_days,
        force_refresh=force_refresh,
    )


@mcp.tool()
async def vut_get_recent_changes(
    force_refresh: bool = True,
    include_pending_actions: bool = True,
):
    """Detect what changed in Studis since the previous snapshot."""
    return await get_studis_client().get_recent_changes(
        force_refresh=force_refresh,
        include_pending_actions=include_pending_actions,
    )


@mcp.tool()
async def vut_get_change_notifications(
    mode: str = "fast",
    force_refresh: bool = True,
    private: bool = False,
    mark_delivered: bool = False,
):
    """Get notifiable Studis changes without sending desktop notifications."""
    if mode not in {"fast", "deep"}:
        raise ValueError("mode must be 'fast' or 'deep'")
    return await get_studis_client().get_change_notifications(
        mode=cast(NotificationMode, mode),
        force_refresh=force_refresh,
        private=private,
        mark_delivered=mark_delivered,
    )


@mcp.tool()
async def vut_get_courses(force_refresh: bool = False):
    """Get courses from the student's VUT Studis electronic index."""
    return await get_studis_client().get_courses(force_refresh=force_refresh)


@mcp.tool()
async def vut_get_grades(course_code: str | None = None, force_refresh: bool = False):
    """Get grades and points from the student's VUT Studis electronic index."""
    client = get_studis_client()
    if course_code:
        return await client.get_course_grades(course_code, force_refresh=force_refresh)
    return await client.get_grades(force_refresh=force_refresh)


@mcp.tool()
async def vut_get_course_points(course_code: str, force_refresh: bool = False):
    """Get points for a specific course code from the VUT Studis electronic index."""
    grades = await get_studis_client().get_course_grades(
        course_code,
        force_refresh=force_refresh,
    )
    return [course_points_payload(grade) for grade in grades]


@mcp.tool()
async def vut_get_course_assessment(course_code: str, force_refresh: bool = False):
    """Get assessment rules, minimum points, and maximum points for a VUT course."""
    return await get_studis_client().get_course_assessment(
        course_code,
        force_refresh=force_refresh,
    )


@mcp.tool()
async def vut_get_assessment_message(
    course_code: str,
    item_order: int,
    entry_order: int | None = None,
    force_refresh: bool = False,
):
    """Get a structured teacher message attached to a VUT course assessment row."""
    return await get_studis_client().get_assessment_message(
        course_code,
        item_order,
        entry_order,
        force_refresh=force_refresh,
    )


@mcp.tool()
async def vut_get_course_terms(course_code: str, force_refresh: bool = False):
    """Get exam/credit terms, registration status, capacity, and points for a VUT course."""
    return await get_studis_client().get_course_terms(course_code, force_refresh=force_refresh)


@mcp.tool()
async def vut_get_course_assignments(course_code: str, force_refresh: bool = False):
    """Get assignments, registration status, deadlines, and submitted files for a VUT course."""
    return await get_studis_client().get_course_assignments(
        course_code,
        force_refresh=force_refresh,
    )


def main() -> None:
    mcp.run()
