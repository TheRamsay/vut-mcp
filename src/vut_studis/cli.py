import asyncio
from typing import Annotated, cast

import typer
from rich.console import Console

from vut_studis.auth import inspect_login_flow, login_with_password
from vut_studis.cache import CacheStore
from vut_studis.client import StudisClient
from vut_studis.config import ENV_PATH, load_settings, set_env_value
from vut_studis.errors import StudisError
from vut_studis.notifications import NotificationMode, send_macos_notification

app = typer.Typer(help="Debug CLI for the standalone VUT Studis client.")
console = Console()


@app.command()
def summary(
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch a compact student summary."""
    result = asyncio.run(StudisClient().get_student_summary(force_refresh=live))
    console.print(result.model_dump(mode="json"))


@app.command("daily-briefing")
def daily_briefing(
    horizon_days: Annotated[
        int,
        typer.Option("--horizon-days", help="Only include actions due within this many days."),
    ] = 7,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
    include_changes: Annotated[
        bool,
        typer.Option("--changes/--no-changes", help="Include recent grade/course changes."),
    ] = True,
) -> None:
    """Fetch the daily assistant briefing."""
    result = asyncio.run(
        StudisClient().get_daily_briefing(
            horizon_days=horizon_days,
            force_refresh=live,
            include_changes=include_changes,
        )
    )
    console.print(result.model_dump(mode="json"))


@app.command("dismiss-briefing-item")
def dismiss_briefing_item(
    action_id: str,
    reason: Annotated[
        str | None,
        typer.Option("--reason", help="Optional reason for dismissing the item."),
    ] = None,
) -> None:
    """Dismiss a briefing item in local memory."""
    result = StudisClient().dismiss_briefing_item(action_id, reason=reason)
    console.print(result.model_dump(mode="json"))


@app.command("course-note-add")
def course_note_add(course_code: str, body: str) -> None:
    """Add a local personal note for a course."""
    result = StudisClient().add_course_note(course_code, body)
    console.print(result.model_dump(mode="json"))


@app.command("course-notes")
def course_notes(course_code: str | None = None) -> None:
    """List local personal course notes."""
    result = StudisClient().get_course_notes(course_code)
    console.print([note.model_dump(mode="json") for note in result])


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
    horizon_days: Annotated[
        int | None,
        typer.Option("--horizon-days", help="Only include actions due within this many days."),
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
            horizon_days=horizon_days,
            force_refresh=live,
        )
    )
    console.print([action.model_dump(mode="json") for action in actions])


@app.command("recent-changes")
def recent_changes(
    live: Annotated[
        bool,
        typer.Option("--live/--cached", help="Fetch live data before comparing snapshots."),
    ] = True,
    include_pending_actions: Annotated[
        bool,
        typer.Option(
            "--pending-actions/--no-pending-actions",
            help="Include slower per-course pending action snapshots.",
        ),
    ] = True,
) -> None:
    """Detect changes since the previous local Studis snapshot."""
    result = asyncio.run(
        StudisClient().get_recent_changes(
            force_refresh=live,
            include_pending_actions=include_pending_actions,
        )
    )
    console.print(result.model_dump(mode="json"))


@app.command("notify-changes")
def notify_changes(
    mode: Annotated[
        str,
        typer.Option("--mode", help="fast checks grades/courses; deep also scans pending actions."),
    ] = "fast",
    live: Annotated[
        bool,
        typer.Option("--live/--cached", help="Fetch live data before comparing snapshots."),
    ] = True,
    private: Annotated[
        bool,
        typer.Option("--private", help="Hide changed values in notification bodies."),
    ] = False,
    send: Annotated[
        bool,
        typer.Option(
            "--send/--no-send",
            help="Try the experimental macOS desktop notifier for new changes.",
        ),
    ] = False,
) -> None:
    """Check Studis changes and optionally try the WIP desktop notifier."""
    client = StudisClient()
    result = asyncio.run(
        client.get_change_notifications(
            mode=_notification_mode(mode),
            force_refresh=live,
            private=private,
            mark_delivered=False,
        )
    )

    delivered_ids: list[str] = []
    if send:
        for notification in result.notifications:
            send_macos_notification(notification)
            delivered_ids.append(notification.id)
        client.record_change_notifications_delivered(delivered_ids)

    console.print(
        {
            **result.model_dump(mode="json"),
            "sent_count": len(delivered_ids),
            "desktop_notifications": "wip" if send else "disabled",
        }
    )


@app.command()
def courses(
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch courses from the electronic index."""
    result = asyncio.run(StudisClient().get_courses(force_refresh=live))
    console.print([course.model_dump(mode="json") for course in result])


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


@app.command("course-status")
def course_status(
    course_code: str,
    mode: Annotated[
        str,
        typer.Option("--mode", help="summary is cheap; full fetches course detail pages."),
    ] = "summary",
    horizon_days: Annotated[
        int | None,
        typer.Option("--horizon-days", help="Only include actions due within this many days."),
    ] = 30,
    live: Annotated[
        bool,
        typer.Option("--live", help="Bypass the local cache and fetch from Studis."),
    ] = False,
) -> None:
    """Fetch the high-level status for one course."""
    if mode not in {"summary", "full"}:
        raise typer.BadParameter("mode must be 'summary' or 'full'")
    status = asyncio.run(
        StudisClient().get_course_status(
            course_code,
            mode=mode,
            horizon_days=horizon_days,
            force_refresh=live,
        )
    )
    console.print(status.model_dump(mode="json"))


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
            "state_snapshots": status.state_snapshots,
            "delivered_notifications": status.delivered_notifications,
            "dismissed_actions": status.dismissed_actions,
            "course_notes": status.course_notes,
            "size_bytes": status.size_bytes,
        }
    )


@app.command("cache-clear")
def cache_clear() -> None:
    """Clear all local cache entries."""
    removed = CacheStore.from_settings(load_settings()).clear()
    console.print({"removed_entries": removed})


def _notification_mode(value: str) -> NotificationMode:
    if value not in {"fast", "deep"}:
        raise typer.BadParameter("mode must be 'fast' or 'deep'")
    return cast(NotificationMode, value)


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

    set_env_value(ENV_PATH, "VUT_SESSION_COOKIE", result.session_cookie)
    console.print(
        {
            "updated": str(ENV_PATH),
            "authenticated": result.authenticated,
            "cookie_names": result.cookie_names,
            "title": result.title,
        }
    )
