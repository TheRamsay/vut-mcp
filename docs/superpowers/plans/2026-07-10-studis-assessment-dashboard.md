# StudIS Assessment Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded, read-only all-course view of StudIS assessment terms using existing per-course term parsing.

**Architecture:** Reuse `StudisClient.get_courses()` and `get_course_terms()`; do not parse the global registration page, because its HTML contains submitted results and variable filtering controls. Build an aggregate model from `CourseTerm` objects, filter by status/time in memory, cap course and term fan-out, and preserve only existing StudIS detail URLs.

**Tech Stack:** Python 3.12, Pydantic, asyncio, pytest, Ruff.

---

### Task 1: Specify aggregate assessment models and sorting

**Files:**
- Modify: `src/vut_studis/models.py`
- Create: `tests/test_assessment_dashboard.py`

- [ ] **Step 1: Inspect `CourseTerm` fields in `models.py` and existing `tests/test_terms_parser.py`; use those names unchanged.**
- [ ] **Step 2: Write failing tests** for `AssessmentDashboardItem` and `AssessmentDashboard` models. An item must include course code/name, term name/kind, start/end timestamps when available, registered state, registration open/close, capacity, points/status when supplied, and `detail_url`.
- [ ] **Step 3: Write pure sorting/filter expectations:** upcoming registered terms first, then registration-open unregistered terms, then others; chronological within class; completed terms excluded by default.

### Task 2: Implement pure conversion/filtering helpers

**Files:**
- Modify: `src/vut_studis/aggregates.py`
- Modify: `tests/test_assessment_dashboard.py`

- [ ] **Step 1: Add `build_assessment_dashboard(...)`** taking `list[CourseTerms]`, injected `now`, `horizon_days`, and `include_past`.
- [ ] **Step 2: Do not infer registration availability from capacity alone.** Expose source registration fields exactly; compute no write action and issue no registration URL request.
- [ ] **Step 3: Apply limits:** accept at most 100 courses from the caller and return at most 500 terms plus a `truncated_count`.
- [ ] **Step 4: Run** `uv run pytest tests/test_assessment_dashboard.py -v`.

### Task 3: Add bounded client and MCP entry points

**Files:**
- Modify: `src/vut_studis/client.py`
- Modify: `src/vut_mcp/server.py`
- Modify: `tests/test_mcp_payloads.py`
- Create: `tests/test_assessment_dashboard_client.py`

- [ ] **Step 1: Add `StudisClient.get_assessment_dashboard(horizon_days=30, include_past=False, force_refresh=False)`.** Retrieve courses once and fan out `get_course_terms()` with a semaphore of 8 concurrent requests; individual `StudisParseError` failures should be skipped and recorded in `unavailable_course_codes`, while auth/transport errors remain fatal.
- [ ] **Step 2: Add `vut_get_assessment_dashboard(...)`** and validate `1 <= horizon_days <= 180`.
- [ ] **Step 3: Write fake-client tests** for the course cap, filtered dashboard, propagated auth error, isolated parser failure, and MCP JSON serialization.
- [ ] **Step 4: Run** `uv run pytest tests/test_terms_parser.py tests/test_assessment_dashboard.py tests/test_assessment_dashboard_client.py tests/test_mcp_payloads.py -v`.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add the tool to the current-tools list** and document that it is view-only; users must use StudIS manually for registration/cancellation.
- [ ] **Step 2: Run** `uv run pytest`, `uv run ruff check .`, and `git diff --check`.
- [ ] **Step 3: Report changed files, validation, limits, and skipped-course behavior to the parent orchestrator. Do not commit or push.**
