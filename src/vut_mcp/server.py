from datetime import date

from fastmcp import FastMCP

from vut_mcp.context import get_studis_client

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
    force_refresh: bool = False,
):
    """Get pending registrations, deadlines, upcoming terms, and unmet point minima."""
    return await get_studis_client().get_pending_actions(
        course_codes=course_codes,
        force_refresh=force_refresh,
    )


@mcp.tool()
async def vut_get_recent_changes(force_refresh: bool = True):
    """Detect what changed in Studis since the previous snapshot."""
    return await get_studis_client().get_recent_changes(force_refresh=force_refresh)


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
    return [
        {
            "course_code": grade.course_code,
            "course_name": grade.course_name,
            "points": grade.points,
            "grade": grade.grade,
            "grade_awarded_on": grade.grade_awarded_on,
            "credit_awarded": grade.credit_awarded,
            "credit_awarded_on": grade.credit_awarded_on,
            "academic_year": grade.academic_year,
            "semester": grade.semester,
        }
        for grade in grades
    ]


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
