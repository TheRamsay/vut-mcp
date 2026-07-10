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
the client uses `VUT_USERNAME` and `VUT_PASSWORD` to log in again and retries the
failed request once. Only cookies applicable to the Studis URL are persisted;
cookies returned by Studis during normal requests are carried forward
automatically. You can still run the command manually to force a new session.

### Moodle setup

Moodle is a separate, read-only data source. Add only the values you intend to
use:

```env
VUT_MOODLE_BASE_URL=https://moodle.vut.cz
VUT_MOODLE_ACCESS_MODE=auto
VUT_MOODLE_TOKEN=
VUT_MOODLE_SESSION_COOKIE=
```

In `auto` mode, a user-provided `VUT_MOODLE_TOKEN` enables Moodle's REST API;
without one, the client uses the authenticated Moodle web UI. `api` requires a
token and fails clearly when a required function is unavailable; `web` never
sends a token. The client may use `VUT_USERNAME` and `VUT_PASSWORD` only to
obtain a Moodle session through VUT SSO. `VUT_MOODLE_SESSION_COOKIE` is separate
from `VUT_SESSION_COOKIE`. No token is created automatically.

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
- `vut_get_moodle_courses`
- `vut_get_moodle_assignments`
- `vut_get_moodle_assignment_files`
- `vut_get_moodle_assignment_file_content`
- `vut_get_moodle_course_resources`

`vut_get_moodle_assignment_file_content` is an explicit, standalone read-only
operation: provide an assignment ID and an exact URL returned by
`vut_get_moodle_assignment_files` for that assignment. It supports only
response MIME types `application/pdf`, `text/plain`, `text/markdown`,
`text/x-markdown`, `text/csv`, and `application/json`. Downloads are capped at
8 MiB; PDFs are capped at 50 pages; returned text defaults to 20,000 characters
and may be increased to at most 50,000 characters. It does not support OCR,
DOCX, images, archives, automatic downloads, indexing, embeddings, or
background sync. Raw attachment bytes and extracted text are never persisted.

`vut_get_moodle_course_resources` lists a selected course's section materials
(file, folder, page, URL, and unknown Moodle activities), including Moodle links
and attached-file metadata. URL activities also include their direct target URL
when Moodle exposes it. The tool never fetches that target, downloads file
bytes, or extracts file content.

The remaining Moodle tools return only course/assignment/file metadata and
Moodle links. No Moodle tool submits work, alters enrolment, or creates tokens.

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
  for course detail pages. Each course can open a rich Raycast detail with
  assessment rows, terms, assignments, actions, and local notes.
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
uv run vut-studis-debug course-status FLP --mode full
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
