# VUT MCP

Minimal scaffold for a VUT Studis integration with two layers:

- `vut_studis`: standalone typed client/parser library for Studis data.
- `vut_mcp`: thin MCP server that exposes `vut_studis` capabilities to a model.

The MVP is intentionally read-only. First target tools are schedule, courses, exams,
grades, and a student summary.

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

## Run

Start the MCP server:

```bash
uv run vut-mcp
```

Use the debug CLI without going through MCP:

```bash
uv run vut-studis-debug summary
uv run vut-studis-debug courses
uv run vut-studis-debug schedule
uv run vut-studis-debug pending-actions --course FLP
uv run vut-studis-debug recent-changes
uv run vut-studis-debug assessment-message FLP --item 2 --entry 1
```

## Authentication

The current MVP uses the VUT SSO username/password flow to refresh a short-lived
Studis session cookie.

Configure credentials locally:

```bash
cp .env.example .env
```

Then edit `.env`:

```env
VUT_USERNAME=your_vut_login
VUT_PASSWORD=your_vut_password
```

Inspect the login pages without submitting credentials:

```bash
uv run vut-studis-debug login-inspect
```

Refresh the local session cookie:

```bash
uv run vut-studis-debug login-refresh-session
```

The command updates `VUT_SESSION_COOKIE` in `.env`. The file is ignored by git.
Session cookies are expected to expire and can be refreshed by running the same
command again.

## Layout

```text
src/
  vut_studis/   # auth, HTTP client, parsers, domain models
  vut_mcp/      # MCP tools and server entrypoint
tests/
  fixtures/     # anonymized HTML/JSON samples for parser tests
```

## MVP Notes

For the first implementation, prefer using an existing browser session cookie over
implementing full SSO login. Keep logs and fixtures anonymized because Studis data is
personal.
