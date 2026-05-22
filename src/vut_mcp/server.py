from datetime import date

from fastmcp import FastMCP

from vut_mcp.context import get_studis_client

mcp = FastMCP("VUT Studis")


@mcp.tool()
async def vut_get_schedule(date_from: date | None = None, date_to: date | None = None):
    """Get the student's VUT Studis schedule."""
    return await get_studis_client().get_schedule(date_from=date_from, date_to=date_to)


@mcp.tool()
async def vut_get_student_summary():
    """Get a compact summary of the student's current Studis state."""
    return await get_studis_client().get_student_summary()


def main() -> None:
    mcp.run()
