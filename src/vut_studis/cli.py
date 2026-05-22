import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from vut_studis.auth import inspect_login_flow, login_with_password
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
