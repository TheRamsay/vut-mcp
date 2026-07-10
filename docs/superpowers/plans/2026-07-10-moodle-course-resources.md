# Moodle Course Resources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven development or executing plans task-by-task. Steps use checkbox syntax for tracking.

**Goal:** List Moodle materials in a selected course, including section context, resource type, Moodle activity link, and file metadata without downloading file contents.

**Architecture:** Extend the independent Moodle package with a course-resource model and parser. In API mode, derive resources from core_course_get_contents. In web mode, parse the Moodle course outline, then visit only Moodle resource and folder activity pages needed to enumerate same-origin plugin-file links. Keep the existing assignment parser unchanged and expose a standalone MCP tool.

**Tech Stack:** Python 3.12, httpx, Pydantic v2, selectolax, FastMCP, pytest, respx, Ruff.

---

## Scope

- Read only: return metadata and links; never download resource bytes or extract resource content.
- Return section title, activity ID, resource name, resource type, Moodle activity URL, and same-origin attached-file metadata.
- Handle Moodle file/resource, folder, page, and URL activities. Unknown activities remain visible as unknown with their Moodle activity link.
- Do not crawl external URLs, recursively traverse folders, parse forums/quizzes/wiki content, or merge resources into DailyBriefing.
- Limits: at most 300 course activities and 500 returned file records per course; fail clearly when exceeded.

## Files

- Modify: src/vut_moodle/models.py, src/vut_moodle/parsers.py, src/vut_moodle/client.py, src/vut_mcp/server.py, README.md.
- Modify tests: tests/test_moodle_parsers.py, tests/test_moodle_client.py, tests/test_mcp_payloads.py, tests/test_imports.py.

### Task 1: Define typed course-resource results

- [ ] Add MoodleCourseResource with course_id, activity_id, section_name, name, resource_type, url, and files.
- [ ] resource_type is Literal file, folder, page, url, unknown.
- [ ] Add model serialization and frozen-model tests.
- [ ] Run uv run pytest tests/test_moodle_client.py -q until PASS.
- [ ] Commit with message: feat: add Moodle course resource models.

### Task 2: Parse course sections and activity metadata safely

- [ ] Add parse_course_resources(html, base_url, course) returning MoodleCourseResource values.
- [ ] Parse only same-origin links with Moodle activity IDs. Identify module types from paths: mod/resource/view.php, mod/folder/view.php, mod/page/view.php, mod/url/view.php; retain other mod paths as unknown.
- [ ] Preserve nearest course-section heading as section_name and deduplicate by activity ID.
- [ ] Include direct pluginfile links associated with an activity, but never request their bytes.
- [ ] Add anonymized fixtures for all supported types, duplicate links, external links, malformed IDs, and section headings.
- [ ] Run uv run pytest tests/test_moodle_parsers.py -q until PASS.
- [ ] Commit with message: feat: parse Moodle course resources.

### Task 3: Enrich file and folder activities without unbounded crawling

- [ ] Add parse_resource_files(html, base_url) that returns only same-origin pluginfile metadata.
- [ ] In web mode, fetch activity pages only for resource and folder types. Do not follow any file URL or link discovered on those pages.
- [ ] Enforce 300 activity and 500 file limits before continuing requests.
- [ ] In API mode, map core_course_get_contents sections and modules into the same model; use returned module contents for file metadata.
- [ ] Add tests for web enrichment, API mapping, limits, and no requests to external or pluginfile URLs.
- [ ] Run uv run pytest tests/test_moodle_client.py tests/test_moodle_parsers.py -q until PASS.
- [ ] Commit with message: feat: load Moodle course resource files.

### Task 4: Add a cache-backed client method and MCP tool

- [ ] Add MoodleClient.get_course_resources(course_id, force_refresh=False).
- [ ] Cache only returned metadata under resource type moodle_course_resources with a 30-minute TTL and a key containing access mode and course ID.
- [ ] Raise MoodleDataError when the course ID is not in current Moodle courses.
- [ ] Add MCP tool vut_get_moodle_course_resources(course_id, force_refresh=False).
- [ ] Test cache separation, unknown course failure, JSON serialization, and MCP forwarding.
- [ ] Run focused tests until PASS.
- [ ] Commit with message: feat: expose Moodle course resources.

### Task 5: Document and validate

- [ ] Document that the tool lists course materials and links but does not download their content.
- [ ] Run uv run pytest -q, uv run ruff check ., and git diff --check.
- [ ] Perform one user-authorized live metadata-only smoke test for KNN. Print only aggregate counts by resource type, with no names, URLs, file bytes, or file content.
- [ ] Commit documentation with message: docs: explain Moodle course resources.

## Self-review

The feature exposes resource metadata only, preserves exact Moodle-origin restrictions, bounds request and result counts, avoids external fetches, and does not overlap the existing explicit assignment-file content tool.
