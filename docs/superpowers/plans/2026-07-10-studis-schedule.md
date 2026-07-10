# StudIS Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `vut_get_schedule` stub with bounded, read-only parsing of the authenticated StudIS personal timetable.

**Architecture:** Fetch only `/studis/student.phtml?sn=osobni_rozvrh`, parse timetable entries into existing immutable `ScheduleItem` models, and filter a normalized event list by inclusive date range in the client. Preserve the exact StudIS course and webinar links only when they are same-origin; never invoke export, registration, or change controls.

**Tech Stack:** Python 3.12, httpx, selectolax, Pydantic, pytest, Ruff.

---

### Task 1: Lock the schedule contract with parser fixtures

**Files:**
- Modify: `tests/fixtures/studis_schedule.html` (anonymized, new)
- Create: `tests/test_schedule_parser.py`

- [ ] **Step 1: Add an anonymized timetable fixture** with two dated classes, one assessment-like entry, a room, an online-link label, and an unrelated malformed row. Use dates in 2026 and generic teacher names; include no real student data.
- [ ] **Step 2: Write failing parser tests** asserting that `parse_schedule_html()` returns typed items with course code/name, start/end timestamps, room, teacher, kind, and a stable same-origin `detail_url` field if the model is extended. Assert malformed rows are skipped and repeated rendered entries are deduplicated.
- [ ] **Step 3: Run** `uv run pytest tests/test_schedule_parser.py -v`; expected result: failure because the current parser raises `NotImplementedError`.

### Task 2: Implement the parser and minimal model extension

**Files:**
- Modify: `src/vut_studis/models.py:27-35`
- Modify: `src/vut_studis/parsers/schedule.py`
- Modify: `src/vut_studis/parsers/common.py` only for reusable Czech date/time parsing helpers

- [ ] **Step 1: Add only fields proven by the fixture/page**, retaining the existing `ScheduleItem` fields. If a detail link is needed, add `detail_url: str | None = None`; do not add calendar/export URLs or opaque HTML.
- [ ] **Step 2: Implement `parse_schedule_html(html, base_url)`** using selectolax. Parse dated timetable blocks, use explicit year from the selected semester/date range when present, normalize whitespace, build timezone-naive local datetimes consistently with existing term parsers, and skip rows without a valid start and end.
- [ ] **Step 3: Enforce safe URLs:** resolve only `vut.cz` URLs through `urljoin`; discard `javascript:`, external webinar links, and arbitrary query URLs.
- [ ] **Step 4: Run** `uv run pytest tests/test_schedule_parser.py -v`; expected result: pass.

### Task 3: Implement client retrieval, filtering, caching, and MCP payload coverage

**Files:**
- Modify: `src/vut_studis/constants.py`
- Modify: `src/vut_studis/client.py:105-116`
- Modify: `src/vut_mcp/server.py:69-73`
- Modify: `tests/test_mcp_payloads.py`
- Create: `tests/test_schedule_client.py`

- [ ] **Step 1: Add `PERSONAL_SCHEDULE_PATH = "/studis/student.phtml?sn=osobni_rozvrh"` and a 30-minute cache key scoped like existing StudIS resources.**
- [ ] **Step 2: Replace the client stub** with a cached fetch that calls the parser exactly once per cache miss. Validate `date_from <= date_to`, then return only entries whose time interval intersects the requested inclusive local-date window. Do not request iCal or every course-detail page.
- [ ] **Step 3: Update the MCP docstring** to describe read-only personal schedule results and date filtering; preserve the existing signature.
- [ ] **Step 4: Write tests** with a fake transport for path selection, cache reuse, invalid date range, and range filtering; write an MCP payload test that serializes dates without mutation.
- [ ] **Step 5: Run** `uv run pytest tests/test_schedule_parser.py tests/test_schedule_client.py tests/test_mcp_payloads.py -v` and `uv run ruff check .`.

### Task 4: Documentation and feature verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the README “stub” label** with a one-line description of returned schedule data and its read-only boundary.
- [ ] **Step 2: Run the complete suite** `uv run pytest` and `uv run ruff check .`.
- [ ] **Step 3: Inspect `git diff --check` and `git status --short`.** Do not commit or push; report exact changed files and validation results to the parent orchestrator.
