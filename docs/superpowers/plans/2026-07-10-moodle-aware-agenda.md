# Moodle-Aware Agenda Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone read-only agenda that combines existing StudIS pending actions with Moodle assignment deadlines without changing the established StudIS daily-briefing contract.

**Architecture:** Keep `vut_studis` independent of Moodle. Create a thin MCP-layer composition tool that calls each existing client, converts only Moodle assignments with a deadline into a neutral agenda item, applies a bounded horizon, and sorts deterministically. No new background synchronization, content extraction, course-name matching, or local persistence.

**Tech Stack:** Python 3.12, Pydantic, FastMCP, pytest, Ruff.

---

### Task 1: Define a neutral cross-source agenda contract

**Files:**
- Create: `src/vut_mcp/models.py`
- Create: `tests/test_agenda_models.py`

- [ ] **Step 1: Write failing tests** for immutable Pydantic models `AgendaSource` (`studis`, `moodle`), `AgendaItem`, and `Agenda`.
- [ ] **Step 2: Define `AgendaItem` fields** exactly as `id`, `source`, `title`, `course_name`, `due_at`, `starts_at`, `severity`, `status`, `url`, and `detail`. All cross-source fields must be optional except `id`, `source`, and `title`; no raw file/content/token fields.
- [ ] **Step 3: Define `Agenda`** as `generated_at`, `horizon_days`, `items`, `studis_count: int`, `moodle_count: int`, and `truncated_count: int`. IDs must be deterministic hashes of source plus stable remote identifiers/URLs.
- [ ] **Step 4: Run** `uv run pytest tests/test_agenda_models.py -v`; expected result: failure until models exist.

### Task 2: Implement pure agenda composition

**Files:**
- Create: `src/vut_mcp/agenda.py`
- Create: `tests/test_agenda.py`

- [ ] **Step 1: Write failing unit tests** that pass existing `PendingAction` and `MoodleAssignment` values to pure functions. Cover: one converted StudIS action, one Moodle deadline, Moodle assignments without `due_at` omitted, horizon exclusion, duplicate-id protection, deterministic time/severity/source ordering, and no mutation of input models.
- [ ] **Step 2: Implement `build_agenda(...)`**. `AgendaItem.severity` is `PendingActionSeverity | None`: preserve it for StudIS items and use `None` for Moodle items. `AgendaItem.status` is `str | None`: use `"action_required"` for StudIS items and preserve Moodle's existing `new`, `draft`, `submitted`, or `unknown` status verbatim. Convert a StudIS action with `detail_url` and either `due_at`/`starts_at`; convert Moodle only when `due_at` is present. Treat submitted Moodle work as informational rather than hiding it. Use `datetime.now(UTC)` injection for tests; do not create a cache or write to SQLite.
- [ ] **Step 3: Limit output to 250 items** after sorting and expose a truncation count; use only first-party metadata returned by current clients.
- [ ] **Step 4: Run** `uv run pytest tests/test_agenda_models.py tests/test_agenda.py -v`.

### Task 3: Add an explicit MCP orchestration tool

**Files:**
- Modify: `src/vut_mcp/server.py`
- Modify: `tests/test_mcp_payloads.py`

- [ ] **Step 1: Add `vut_get_agenda(horizon_days: int = 14, force_refresh: bool = False)`.** Validate `1 <= horizon_days <= 90` before client requests.
- [ ] **Step 2: Fetch in parallel with `asyncio.gather`**: `StudisClient.get_pending_actions(horizon_days=...)` and `MoodleClient.get_assignments(course_id=None, ...)`. Do not call resource/content tools or fetch external URLs.
- [ ] **Step 3: Write fake-client MCP tests** proving both client calls occur with the supplied freshness flag and that validation rejects zero/91 days without calls.
- [ ] **Step 4: Run** `uv run pytest tests/test_agenda_models.py tests/test_agenda.py tests/test_mcp_payloads.py -v` and `uv run ruff check .`.

### Task 4: Document and verify the boundary

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document `vut_get_agenda`** as a standalone, read-only cross-source timeline; explicitly say it does not replace or write daily briefings and never registers, submits, downloads, or fetches external resource targets.
- [ ] **Step 2: Run** `uv run pytest`, `uv run ruff check .`, and `git diff --check`.
- [ ] **Step 3: Report to the parent orchestrator** with changed files, all validation output, and any unresolved ambiguity. Do not commit or push.
