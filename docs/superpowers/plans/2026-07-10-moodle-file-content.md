# Moodle File Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven development or executing plans task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add an explicit read-only MCP tool that extracts bounded text from one previously listed Moodle PDF or text attachment.

**Architecture:** The caller supplies an assignment ID and exact attachment URL returned by the current file-list tool. The client verifies membership before an origin-scoped transport streams a bounded response into memory. A pure extraction module supports only PDF and UTF-8 text. Raw bytes and extracted text are never written to SQLite, .env, or the filesystem.

**Tech Stack:** Python 3.12, httpx streaming, Pydantic v2, pypdf, FastMCP, pytest, respx, Ruff.

---

## Contract

- Supported response MIME types: application/pdf, text/plain, text/markdown, text/x-markdown, text/csv, and application/json.
- No automatic scanning, indexing, downloads, OCR, or token creation.
- Limits: 8 MiB decoded bytes, 50 PDF pages, 20,000 returned characters by default, and 50,000 maximum caller-requested characters.
- Reject HTML, Office documents, archives, images, executables, unknown binary data, off-origin URLs, non-pluginfile Moodle paths, and URLs not listed for the supplied assignment.
- DOCX is deliberately deferred because ZIP and XML processing widens the resource-security surface.

## Files

- Modify: pyproject.toml, uv.lock, src/vut_moodle/models.py, src/vut_moodle/errors.py, src/vut_moodle/transport.py, src/vut_moodle/client.py, src/vut_moodle/__init__.py, src/vut_mcp/server.py, README.md.
- Create: src/vut_moodle/extraction.py and tests/test_moodle_extraction.py.
- Modify tests: tests/test_moodle_transport.py, tests/test_moodle_client.py, tests/test_mcp_payloads.py, tests/test_imports.py.

### Task 1: Add result types and PDF dependency

- [ ] Add pypdf>=5.0,<6 to runtime dependencies and run uv lock.
- [ ] Add MoodleContentError subclassing MoodleError.
- [ ] Add this frozen Pydantic model:

~~~python
class MoodleFileContent(MoodleModel):
    file: MoodleFile
    content_type: str
    text: str
    text_truncated: bool
    bytes_downloaded: int
    extractor: Literal["pdf", "text"]
~~~

- [ ] Add failing tests for JSON serialization and pypdf import; run uv run pytest tests/test_moodle_extraction.py -q until PASS.
- [ ] Commit with message: feat: add Moodle file content types.

### Task 2: Stream only Moodle plugin files within a byte limit

- [ ] Add MoodleTransport.download_file(path: str, *, max_bytes: int) returning tuple[bytes, str | None].
- [ ] Reuse exact-origin resolution and additionally require the parsed path to start with /pluginfile.php/.
- [ ] Use AsyncClient.stream with normal Moodle session cookies. Reject Content-Length over 8 MiB and stop after decoded chunks exceed max_bytes.
- [ ] Reject final login or off-origin redirects before returning bytes. Preserve same-origin cookie rotations only.
- [ ] Add tests for no-request rejection of evil and non-pluginfile URLs, declared and chunked size limits, one refresh retry, and off-origin redirect cookie isolation.
- [ ] Run uv run pytest tests/test_moodle_transport.py -q until PASS; commit with message: feat: stream bounded Moodle attachments.

### Task 3: Extract PDF and UTF-8 text in memory

- [ ] Create extraction.py with extract_file_content(file, data, content_type, max_characters, max_pdf_pages=50).
- [ ] Normalize response MIME by removing parameters. Accept only the contract MIME types.
- [ ] Text decoding uses utf-8-sig with replacement errors.
- [ ] PDF extraction requires a percent-PDF signature, reads from BytesIO using PdfReader, rejects more than 50 pages, concatenates page.extract_text() or empty text, and converts malformed-file exceptions to MoodleContentError.
- [ ] Return MoodleFileContent with the selected text slice and an explicit truncation boolean.
- [ ] Test UTF-8 BOM, replacement decoding, truncation, MIME rejection, malformed PDF, page limit, and anonymous PDF extraction. No personal Moodle fixture may be stored.
- [ ] Run uv run pytest tests/test_moodle_extraction.py -q until PASS; commit with message: feat: extract Moodle PDF and text content.

### Task 4: Enforce assignment membership and add the MCP tool

- [ ] Add MoodleClient.get_assignment_file_content(assignment_id, file_url, *, max_characters=20000).
- [ ] Validate 1 <= max_characters <= 50000, load assignment files, require exact URL equality, stream the file with an 8 MiB limit, then call extraction through asyncio.to_thread.
- [ ] Do not call CacheStore from this method. Two calls intentionally result in two downloads.
- [ ] Add MCP tool vut_get_moodle_assignment_file_content(assignment_id, file_url, max_characters=20000).
- [ ] Test URL membership, character limits, no-cache behavior, JSON serialization, and MCP parameter forwarding.
- [ ] Run focused client and MCP tests until PASS; commit with message: feat: expose Moodle file content extraction.

### Task 5: Document and validate

- [ ] Document explicit invocation, supported formats, limits, no OCR, and no raw/text persistence.
- [ ] Add a public import test for extract_file_content.
- [ ] Run uv run pytest -q, uv run ruff check ., and git diff --check.
- [ ] Perform a live smoke test only with a user-authorized small listed attachment, temporary cookie persistence, disabled cache, and output limited to MIME, byte count, truncation, and character count.
- [ ] Commit with message: docs: explain Moodle file content extraction.

## Self-review

This plan makes file content access explicit, verifies assignment-file membership, preserves current origin/session isolation, enforces streaming and parser limits, and never persists personal document bytes or text. OCR, DOCX, archives, images, embeddings, and background synchronization are out of scope.
