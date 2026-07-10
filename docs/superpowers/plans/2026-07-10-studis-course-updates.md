# StudIS Course Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the read-only StudIS “Aktuality z předmětu” feed as typed, bounded course updates with safe StudIS links.

**Architecture:** Fetch exactly `/studis/student.phtml?sn=aktuality_predmet`; parse only the displayed table rows, course metadata, date, title, author, and same-origin announcement/course URLs. Provide a separate query tool rather than adding this feed to notifications or daily briefing in this iteration.

**Tech Stack:** Python 3.12, selectolax, Pydantic, httpx, pytest, Ruff.

---

### Task 1: Create anonymized fixture and parser contract

**Files:**
- Create: `tests/fixtures/studis_course_updates.html`
- Create: `tests/test_course_updates_parser.py`
- Modify: `src/vut_studis/models.py`

- [ ] **Step 1: Build a fixture** with two table rows, Czech headers `Datum`, `Aktualita`, `Předmět`, `Vystavil`, a relative announcement URL, a same-origin course URL, one external URL, and a malformed row. Use non-real titles/authors.
- [ ] **Step 2: Write failing tests** for immutable `CourseUpdate` with `id`, `published_at`, `title`, `course_code`, `course_name`, `author`, `url`, and `course_url`; and `CourseUpdates` with `items` and `truncated_count`.
- [ ] **Step 3: Assert parser behavior:** Czech date parsing, whitespace cleanup, same-origin URL resolution, rejection of external/javascript links, malformed-row skip, newest-first sort, and deterministic deduplication.

### Task 2: Implement parser safely

**Files:**
- Create: `src/vut_studis/parsers/course_updates.py`
- Modify: `src/vut_studis/parsers/__init__.py` only if imports are centrally exported
- Modify: `tests/test_course_updates_parser.py`

- [ ] **Step 1: Implement `parse_course_updates_html(html, base_url)`** using header-label matching rather than table position. Generate an ID from stable date/title/course/url values using SHA-256 truncated to a non-secret identifier.
- [ ] **Step 2: Use shared URL/date helpers where they already exist; otherwise add narrow helpers to `parsers/common.py`.** Do not parse announcement body content or follow its link.
- [ ] **Step 3: Run** `uv run pytest tests/test_course_updates_parser.py -v`.

### Task 3: Add client cache, query limits, and MCP tool

**Files:**
- Modify: `src/vut_studis/constants.py`
- Modify: `src/vut_studis/client.py`
- Modify: `src/vut_mcp/server.py`
- Create: `tests/test_course_updates_client.py`
- Modify: `tests/test_mcp_payloads.py`

- [ ] **Step 1: Add `COURSE_UPDATES_PATH` and a 30-minute cached `get_course_updates(limit=100, force_refresh=False)`.** Validate `1 <= limit <= 200`; parse once, then slice only in memory.
- [ ] **Step 2: Add `vut_get_course_updates(limit=100, force_refresh=False)`** with a docstring that explicitly promises metadata/links only and no announcement-body fetch.
- [ ] **Step 3: Test** path selection, cache reuse, limit validation, slicing/truncation, and JSON payload serialization using fake transport/client fixtures.
- [ ] **Step 4: Run** `uv run pytest tests/test_course_updates_parser.py tests/test_course_updates_client.py tests/test_mcp_payloads.py -v` and `uv run ruff check .`.

### Task 4: README and full verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the new tool** as an explicit, standalone feed; no daily-briefing merge, notifications, crawling, or write actions.
- [ ] **Step 2: Run** `uv run pytest`, `uv run ruff check .`, and `git diff --check`.
- [ ] **Step 3: Report to the parent orchestrator. Do not commit or push.**
