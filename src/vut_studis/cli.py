import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from vut_studis.auth import inspect_login_flow, login_with_password
from vut_studis.cache import CacheStore
from vut_studis.client import StudisClient
from vut_studis.config import load_settings
from vut_studis.errors import StudisError

app = typer.Typer(help="Debug CLI for the standalone VUT Studis client.")
console = Console()
ENV_PATH = Path(".env")


@app.command()
def summary() -> None:
    """Fetch a compact student summary."""
    console.print("Student summary is not implemented yet.")


@app.command()
def schedule(
    date_from: Annotated[str | None, typer.Option("--from", help="Start date, YYYY-MM-DD.")] = None,
    date_to: Annotated[str | None, typer.Option("--to", help="End date, YYYY-MM-DD.")] = None,
) -> None:
    """Fetch schedule data."""
    console.print(
        {
            "status": "not_implemented",
            "date_from": date_from,
            "date_to": date_to,
        }
    )


@app.command("pending-actions")
def pending_actions(
    course_code: Annotated[
        list[str] | None,
        typer.Option("--course", help="Limit to one or more course codes."),
    ] = None,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch actionable registration, deadline, and minimum-point warnings."""
    actions = asyncio.run(
        StudisClient().get_pending_actions(
            course_codes=course_code,
            force_refresh=live,
        )
    )
    console.print([action.model_dump(mode="json") for action in actions])


@app.command()
def grades(
    course_code: Annotated[
        str | None,
        typer.Option("--course", help="Filter by course code."),
    ] = None,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch grades and points from the electronic index."""
    client = StudisClient()
    grades_result = asyncio.run(
        client.get_course_grades(course_code, force_refresh=live)
        if course_code
        else client.get_grades(force_refresh=live)
    )
    console.print([grade.model_dump(mode="json") for grade in grades_result])


@app.command("course-assessment")
def course_assessment(
    course_code: str,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch assessment rules for a single course."""
    assessment = asyncio.run(StudisClient().get_course_assessment(course_code, force_refresh=live))
    console.print(assessment.model_dump(mode="json"))


@app.command("assessment-message")
def assessment_message(
    course_code: str,
    item_order: Annotated[int, typer.Option("--item", help="Assessment item order.")],
    entry_order: Annotated[
        int | None,
        typer.Option("--entry", help="Assessment entry order, when the message is on a sub-row."),
    ] = None,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch a teacher note/message attached to an assessment row."""
    message = asyncio.run(
        StudisClient().get_assessment_message(
            course_code,
            item_order,
            entry_order,
            force_refresh=live,
        )
    )
    console.print(message.model_dump(mode="json"))


@app.command("course-terms")
def course_terms(
    course_code: str,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch exam and credit terms for a single course."""
    terms = asyncio.run(StudisClient().get_course_terms(course_code, force_refresh=live))
    console.print(terms.model_dump(mode="json"))


@app.command("course-assignments")
def course_assignments(
    course_code: str,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch assignments and submitted file status for a single course."""
    assignments = asyncio.run(
        StudisClient().get_course_assignments(course_code, force_refresh=live)
    )
    console.print(assignments.model_dump(mode="json"))


@app.command("cache-status")
def cache_status() -> None:
    """Show local cache status."""
    status = CacheStore.from_settings(load_settings()).status()
    console.print(
        {
            "path": str(status.path),
            "enabled": status.enabled,
            "entries": status.entries,
            "expired_entries": status.expired_entries,
            "size_bytes": status.size_bytes,
        }
    )


@app.command("cache-clear")
def cache_clear() -> None:
    """Clear all local cache entries."""
    removed = CacheStore.from_settings(load_settings()).clear()
    console.print({"removed_entries": removed})


@app.command("login-inspect")
def login_inspect() -> None:
    """Inspect the Studis login flow without submitting credentials."""
    snapshots = asyncio.run(inspect_login_flow())
    for index, snapshot in enumerate(snapshots, start=1):
        console.rule(f"Step {index}")
        console.print(
            {
                "requested_url": snapshot.requested_url,
                "final_url": snapshot.final_url,
                "status_code": snapshot.status_code,
                "redirect_chain": snapshot.redirect_chain,
                "title": snapshot.title,
            }
        )
        for form_index, form in enumerate(snapshot.forms, start=1):
            console.print(
                {
                    "form": form_index,
                    "method": form.method,
                    "action": form.action,
                    "fields": [
                        {
                            "name": field.name,
                            "type": field.field_type,
                            "value_present": field.value_present,
                        }
                        for field in form.fields
                    ],
                }
            )


@app.command("login-check")
def login_check() -> None:
    """Try username/password login and print only sanitized session metadata."""
    try:
        result = asyncio.run(login_with_password())
    except StudisError as error:
        raise typer.BadParameter(str(error)) from error

    console.print(
        {
            "final_url": result.final_url,
            "status_code": result.status_code,
            "authenticated": result.authenticated,
            "cookie_names": result.cookie_names,
            "title": result.title,
        }
    )


@app.command("login-refresh-session")
def login_refresh_session() -> None:
    """Login and update VUT_SESSION_COOKIE in the local .env file."""
    try:
        result = asyncio.run(login_with_password())
    except StudisError as error:
        raise typer.BadParameter(str(error)) from error

    if not result.authenticated:
        raise typer.BadParameter("Login did not reach an authenticated Studis page.")

    _set_env_value(ENV_PATH, "VUT_SESSION_COOKIE", result.session_cookie)
    console.print(
        {
            "updated": str(ENV_PATH),
            "authenticated": result.authenticated,
            "cookie_names": result.cookie_names,
            "title": result.title,
        }
    )


def _set_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    replacement = f'{key}="{_escape_env_value(value)}"'

    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)

    path.write_text("\n".join(lines) + "\n")


def _escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
