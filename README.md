# VUT MCP

Read-only personal assistant layer for VUT Studis. The project parses Studis HTML
pages into typed Python models, exposes them as MCP tools for LLM clients, and
ships a native Raycast extension for quick daily use.

## What It Does

- Reads courses, grades, total points, credits, and completion status from the
  electronic index.
- Parses course details: assessment rules, minimum/maximum points, exam terms,
  assignment deadlines, submitted files, and teacher assessment messages.
- Builds pending actions for missed registrations, upcoming terms, assignment
  deadlines, and unmet point minima.
- Records local snapshots and reports what changed since the previous check.
- Builds a daily briefing and stores local memory such as dismissed briefing
  items and personal course notes.
- Keeps data local; credentials, cookies, and cache files are ignored by git.

## Architecture

- `vut_studis`: standalone client/parser library for Studis HTML.
- `vut_mcp`: thin FastMCP server exposing the library to model clients.
- `raycast-extension`: native Raycast UI for fast personal workflows.
- SQLite cache: local cache and snapshot storage, defaulting to the user cache
  directory unless `VUT_CACHE_PATH` is set.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

Edit `.env`:

```env
VUT_BASE_URL=https://www.vut.cz
VUT_USERNAME=your_vut_login
VUT_PASSWORD=your_vut_password
```

Refresh the local Studis session cookie:

```bash
uv run vut-studis-debug login-refresh-session
```

The command updates `VUT_SESSION_COOKIE` in `.env`. Studis sessions expire, so
the client automatically refreshes the cookie and retries once when
`VUT_USERNAME` and `VUT_PASSWORD` are configured. You can still run the command
manually when you want to refresh the session explicitly.

## MCP

Start the server:

```bash
uv run vut-mcp
```

Current tools:

- `vut_get_student_summary`
- `vut_get_daily_briefing`
- `vut_dismiss_briefing_item`
- `vut_add_course_note`
- `vut_get_course_notes`
- `vut_get_pending_actions`
- `vut_get_recent_changes`
- `vut_get_change_notifications`
- `vut_get_courses`
- `vut_get_grades`
- `vut_get_course_points`
- `vut_get_course_status`
- `vut_get_course_assessment`
- `vut_get_course_terms`
- `vut_get_course_assignments`
- `vut_get_assessment_message`
- `vut_get_schedule` *(stub; parser not implemented yet)*

For Codex, configure the MCP server with this command:

```bash
uv --directory /Users/ramsay/dev/vut-mcp run vut-mcp
```

## Raycast

Run the native extension in development mode:

```bash
cd raycast-extension
pnpm install
pnpm dev
```

Commands:

- `VUT Today`: pending actions grouped by severity.
- `VUT Grades`: points, grades, credits, completion status, and `Open in Studis`
  for course detail pages.
- `VUT Changes`: fast snapshot diff for courses and grades/points since the
  previous check.
- `VUT Check Now`: no-view command that checks grade/point changes and shows a
  Raycast toast.

Each command has preferences for repository path and `uv` path. Defaults are set
for this local checkout.

## Notifications

Desktop macOS banners are currently **WIP/experimental**. Raycast toasts are the
supported notification UI for now.

Build the native macOS notification helper:

```bash
./scripts/build-macos-notifier.sh
./scripts/install-macos-notifier.sh
```

The helper app is installed at `~/Applications/VUT Studis Notifier.app`. It is
not used by default because macOS Notification Center and windowing behavior has
been inconsistent in local testing.

To explicitly try the WIP desktop path:

```bash
VUT_ENABLE_DESKTOP_NOTIFICATIONS=1 uv run vut-studis-debug notify-changes --send
```

## Debug CLI

Use the CLI to inspect data without MCP or Raycast:

```bash
uv run vut-studis-debug summary
uv run vut-studis-debug daily-briefing --horizon-days 7
uv run vut-studis-debug dismiss-briefing-item pending:abc123 --reason "handled"
uv run vut-studis-debug course-note-add FLP "Check exam registration."
uv run vut-studis-debug course-notes FLP
uv run vut-studis-debug pending-actions --horizon-days 14
uv run vut-studis-debug recent-changes
uv run vut-studis-debug recent-changes --no-pending-actions
uv run vut-studis-debug notify-changes --mode fast
uv run vut-studis-debug notify-changes --mode deep --private
uv run vut-studis-debug grades
uv run vut-studis-debug course-status FLP
uv run vut-studis-debug course-assessment FLP
uv run vut-studis-debug course-terms FLP
uv run vut-studis-debug course-assignments FLP
uv run vut-studis-debug assessment-message FLP --item 2 --entry 1
```

The experimental desktop path falls back to `terminal-notifier` when available:

```bash
brew install terminal-notifier
```

Without either notifier, the CLI falls back to AppleScript notifications.

Cache helpers:

```bash
uv run vut-studis-debug cache-status
uv run vut-studis-debug cache-clear
```

## Development

```bash
uv run ruff check .
uv run pytest

cd raycast-extension
pnpm typecheck
pnpm lint
pnpm build
```

Keep fixtures, logs, and screenshots anonymized. Studis data can contain personal
course records and teacher comments.
