# Moodle Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only VUT Moodle data source that exposes a student's Moodle courses, assignment deadlines, and downloadable-file metadata through the existing MCP server.

**Architecture:** Introduce an independent `vut_moodle` package alongside `vut_studis`, with its own settings, authenticated session, typed models, cache keys, parsers, and MCP context getter. Moodle authentication reuses only the generic VUT SSO form-flow mechanics; Moodle cookies and optional web-service tokens are always stored separately from Studis cookies. In `auto` mode the client uses Moodle REST only when `VUT_MOODLE_TOKEN` is explicitly configured, and otherwise falls back to the authenticated Moodle web UI.

**Tech Stack:** Python 3.12, httpx, Pydantic v2, pydantic-settings, selectolax, FastMCP, SQLite cache, pytest, pytest-asyncio, respx, Ruff.

---

## Verified technical facts (2026-07-10)

- `https://moodle.vut.cz/` uses VUT's OIDC/SSO login (`id.vut.cz`) and, after a successful credential login, redirects to `https://moodle.vut.cz/local/customfrontpage/index.php` with a host-only `MoodleSession` cookie.
- `https://moodle.vut.cz/webservice/rest/server.php` is reachable and rejects an intentionally invalid token. The endpoint therefore exists, but this probe does **not** prove which functions are enabled for a student.
- `https://moodle.vut.cz/admin/webservice/documentation.php` returns `404` for a normal authenticated user. Do not scrape or depend on the site's generated API documentation.
- Do not call `admin/tool/mobile/launch.php` during discovery or normal login: it can mint a token. API-token creation must be a separate, explicit, user-authorized action and is not part of this MVP.
- The public Moodle login's final OIDC hand-off uses a browser-style HTML `POST` back to `moodle.vut.cz`; the existing Studis login helper currently follows redirects and meta refreshes but does not submit that final OIDC form.

## MVP contract and non-goals

- Read only. Never submit an assignment, create a token, change enrolment, or upload/download an attachment automatically.
- Return assignment and file **metadata plus Moodle URLs**. Do not fetch, cache, index, or return file bytes in this feature.
- Add standalone Moodle MCP tools first. Do not widen `DailyBriefing`, `PendingAction`, Raycast views, notifications, or the Studis course-status model in this MVP; those changes should follow once real Moodle data is stable.
- API mode is opt-in through `VUT_MOODLE_TOKEN`. `auto` means API when that token is present; otherwise web mode. `api` fails clearly when the token is absent or a required function is forbidden. `web` never sends a token.

## File structure

| Path | Responsibility |
|---|---|
| `src/vut_studis/auth.py` | Generic VUT SSO form runner plus the existing Studis-specific wrapper. |
| `src/vut_studis/transport.py` | Repair the current syntax typo before any import/test work. No Moodle responsibility. |
| `src/vut_studis/config.py` | Extend shared settings with Moodle base URL, access mode, token, and session cookie. |
| `src/vut_moodle/__init__.py` | Public `MoodleClient` export. |
| `src/vut_moodle/auth.py` | Moodle entry URL, successful-login predicate, and Moodle-session refresh wrapper. |
| `src/vut_moodle/errors.py` | Typed, non-secret configuration, authentication, API, and parsing errors. |
| `src/vut_moodle/transport.py` | Exact-origin Moodle session requests, cookie persistence, refresh and login detection. |
| `src/vut_moodle/models.py` | Frozen Pydantic models for courses, assignments, and file metadata. |
| `src/vut_moodle/client.py` | Public read methods, mode selection, cache integration, REST calls, and web fallback orchestration. |
| `src/vut_moodle/parsers.py` | Tight, page-specific HTML parsers for the dashboard, course contents, and assignment page. |
| `src/vut_mcp/context.py` | Construct a Moodle client separately from the Studis client. |
| `src/vut_mcp/server.py` | Add three standalone read-only Moodle tools. |
| `.env.example`, `README.md` | Configuration, credential handling, tool list, and explicit no-download policy. |
| `tests/test_moodle_auth.py` | OIDC form-post and target-scoped cookie behavior. |
| `tests/test_moodle_transport.py` | Session refresh, origin isolation, and rotating-cookie behavior. |
| `tests/test_moodle_client.py` | API mode, fallback mode, forbidden API errors, and cache behavior. |
| `tests/test_moodle_parsers.py` | Anonymized Moodle dashboard/course/assignment HTML fixtures embedded in tests. |
| `tests/test_mcp_context.py`, `tests/test_mcp_payloads.py` | Context construction and JSON-serializable tool return values. |

### Task 1: Restore a green import/test baseline

**Files:**
- Modify: `src/vut_studis/transport.py:1`
- Test: `tests/test_imports.py`

- [ ] **Step 1: Add a regression test that imports the transport module**

```python
def test_studis_transport_imports() -> None:
    from vut_studis.transport import StudisTransport

    assert StudisTransport.__name__ == "StudisTransport"
```

- [ ] **Step 2: Run the focused test and verify the current failure**

Run: `uv run pytest tests/test_imports.py -q`

Expected: FAIL with `SyntaxError: invalid syntax` pointing at `/import time` in `src/vut_studis/transport.py`.

- [ ] **Step 3: Correct only the invalid import token**

```python
import time
```

The first line must be exactly `import time`, with no leading slash. Do not alter the session-refresh implementation in this task.

- [ ] **Step 4: Re-run the focused test**

Run: `uv run pytest tests/test_imports.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated repair**

```bash
git add src/vut_studis/transport.py tests/test_imports.py
git commit -m "fix: restore Studis transport import"
```

### Task 2: Make the VUT SSO form runner reusable for Moodle's OIDC hand-off

**Files:**
- Modify: `src/vut_studis/auth.py`
- Test: `tests/test_auth.py`
- Test: `tests/test_moodle_auth.py`

- [ ] **Step 1: Write failing tests for a target-scoped generic SSO login**

```python
@pytest.mark.asyncio
@respx.mock
async def test_login_via_vut_sso_submits_oidc_form_to_moodle() -> None:
    # Mock: Moodle entry -> IdP login form -> password form -> hidden OIDC form.
    # Assert that only the hidden OIDC fields are POSTed to moodle.vut.cz.
    result = await login_via_vut_sso(
        _settings(),
        entry_url="https://moodle.vut.cz/auth/oidc/?source=loginpage",
        target_origin="https://moodle.vut.cz",
        authenticated=lambda response: response.url.path == "/local/customfrontpage/index.php",
    )

    assert result.authenticated is True
    assert result.session_cookie == "MoodleSession=moodle-session"
```

```python
def test_target_form_post_rejects_oidc_fields_for_another_origin() -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://id.vut.cz/complete"),
        html=(
            '<form method="post" action="https://evil.example/callback">'
            '<input name="state" value="state-1">'
            '<input name="code" value="code-1">'
            "</form>"
        ),
    )

    with pytest.raises(StudisAuthError, match="target origin"):
        _target_form_post(response, target_origin="https://moodle.vut.cz")
```

- [ ] **Step 2: Run the new tests and verify they fail because `login_via_vut_sso` is missing**

Run: `uv run pytest tests/test_auth.py tests/test_moodle_auth.py -q`

Expected: FAIL with an import error for `login_via_vut_sso`.

- [ ] **Step 3: Add the generic runner and preserve the existing Studis API**

```python
async def login_via_vut_sso(
    settings: Settings,
    *,
    entry_url: str,
    target_origin: str,
    authenticated: Callable[[httpx.Response], bool],
) -> LoginAttemptResult:
    if not settings.username or not settings.password:
        raise StudisAuthError("VUT_USERNAME and VUT_PASSWORD must be configured in .env.")
    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.http_timeout_seconds) as client:
        response = await _follow_login_meta_refresh(client, await client.get(entry_url))
        action, payload = _form_values(response.text, str(response.url), required_field="login")
        payload["login"] = settings.username
        response = await _follow_login_meta_refresh(client, await client.post(action, data=payload))
        action, payload = _form_values(response.text, str(response.url), required_field="passwd")
        payload["passwd"] = settings.password
        _set_fingerprint_payload(payload)
        response = await _follow_login_meta_refresh(client, await client.post(action, data=payload))
        if form_post := _target_form_post(response, target_origin=target_origin):
            action, payload = form_post
            response = await _follow_login_meta_refresh(client, await client.post(action, data=payload))
        return LoginAttemptResult(
            final_url=str(response.url), status_code=response.status_code,
            authenticated=authenticated(response),
            cookie_names=sorted(cookie.name for cookie in client.cookies.jar),
            session_cookie=_cookie_header_for_url(client.cookies.jar, entry_url),
            title=_parse_title(response.text),
        )


async def login_with_password(settings: Settings | None = None) -> LoginAttemptResult:
    settings = settings or load_settings()
    return await login_via_vut_sso(
        settings,
        entry_url=urljoin(str(settings.base_url), ELECTRONIC_INDEX_PATH),
        target_origin=str(settings.base_url),
        authenticated=_looks_authenticated,
    )
```

Implement `_target_form_post()` with these exact guards: form method is `post`, all inputs have names, the action's normalized origin equals `target_origin`, and the form includes `state`. Raise `StudisAuthError` for a `state` form whose action is off-origin. Keep the current username/password and fingerprint payload code unchanged.

- [ ] **Step 4: Run all authentication tests**

Run: `uv run pytest tests/test_auth.py tests/test_moodle_auth.py -q`

Expected: PASS; retain all existing Studis assertions about exclusion of `id.vut.cz` cookies.

- [ ] **Step 5: Commit the shared SSO capability**

```bash
git add src/vut_studis/auth.py tests/test_auth.py tests/test_moodle_auth.py
git commit -m "feat: support VUT SSO target form posts"
```

### Task 3: Add explicit Moodle configuration and typed domain models

**Files:**
- Modify: `src/vut_studis/config.py`
- Create: `src/vut_moodle/__init__.py`
- Create: `src/vut_moodle/errors.py`
- Create: `src/vut_moodle/models.py`
- Modify: `.env.example`
- Test: `tests/test_moodle_client.py`

- [ ] **Step 1: Write settings/model tests**

```python
def test_moodle_settings_default_to_safe_web_fallback() -> None:
    settings = Settings(VUT_BASE_URL="https://www.vut.cz")

    assert str(settings.moodle_base_url) == "https://moodle.vut.cz/"
    assert settings.moodle_access_mode == "auto"
    assert settings.moodle_token is None
    assert settings.moodle_session_cookie is None


def test_moodle_assignment_is_frozen_and_serializable() -> None:
    assignment = MoodleAssignment(id=17, course_id=3, name="Project", url="https://moodle.vut.cz/mod/assign/view.php?id=17")

    assert assignment.model_dump(mode="json")["name"] == "Project"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run pytest tests/test_moodle_client.py -q`

Expected: FAIL because the Moodle settings and models do not exist.

- [ ] **Step 3: Add configuration and models**

```python
class Settings(BaseSettings):
    # Existing fields remain unchanged.
    moodle_base_url: AnyHttpUrl = Field(
        default="https://moodle.vut.cz",
        alias="VUT_MOODLE_BASE_URL",
    )
    moodle_access_mode: Literal["auto", "api", "web"] = Field(
        default="auto",
        alias="VUT_MOODLE_ACCESS_MODE",
    )
    moodle_token: str | None = Field(default=None, alias="VUT_MOODLE_TOKEN")
    moodle_session_cookie: str | None = Field(
        default=None,
        alias="VUT_MOODLE_SESSION_COOKIE",
    )
```

Add `from typing import Literal` to `src/vut_studis/config.py`.

```python
class MoodleError(Exception):
    pass


class MoodleConfigurationError(MoodleError):
    pass


class MoodleAuthError(MoodleError):
    pass


class MoodleApiError(MoodleError):
    def __init__(self, function: str, message: str) -> None:
        super().__init__(f"Moodle API {function}: {message}")
        self.function = function


class MoodleDataError(MoodleError):
    pass
```

```python
class MoodleFile(MoodleModel):
    name: str
    url: str
    size_bytes: int | None = None
    mimetype: str | None = None
    modified_at: datetime | None = None


class MoodleCourse(MoodleModel):
    id: int
    name: str
    short_name: str | None = None
    url: str


class MoodleAssignment(MoodleModel):
    id: int
    course_id: int
    course_name: str | None = None
    name: str
    url: str
    due_at: datetime | None = None
    cutoff_at: datetime | None = None
    submission_status: Literal["new", "draft", "submitted", "unknown"] = "unknown"
    files: list[MoodleFile] = Field(default_factory=list)
```

Add these empty keys to `.env.example` only: `VUT_MOODLE_BASE_URL`, `VUT_MOODLE_ACCESS_MODE`, `VUT_MOODLE_TOKEN`, and `VUT_MOODLE_SESSION_COOKIE`. Never copy a real value.

- [ ] **Step 4: Run focused model/settings tests**

Run: `uv run pytest tests/test_moodle_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the configuration boundary**

```bash
git add src/vut_studis/config.py src/vut_moodle .env.example tests/test_moodle_client.py
git commit -m "feat: add Moodle settings and models"
```

### Task 4: Implement a separately persisted, origin-scoped Moodle session

**Files:**
- Create: `src/vut_moodle/auth.py`
- Create: `src/vut_moodle/transport.py`
- Test: `tests/test_moodle_auth.py`
- Test: `tests/test_moodle_transport.py`

- [ ] **Step 1: Add transport behavior tests**

```python
@pytest.mark.asyncio
@respx.mock
async def test_moodle_transport_refreshes_once_and_persists_only_moodle_cookie(tmp_path: Path) -> None:
    settings = _settings(moodle_session_cookie="MoodleSession=expired")
    # First course request returns Moodle's login page; mocked SSO refresh returns MoodleSession=fresh.
    transport = MoodleTransport(settings, env_path=tmp_path / ".env")

    response = await transport.get_response("/my/")

    assert response.status_code == 200
    assert settings.moodle_session_cookie == "MoodleSession=fresh"
    assert "VUT_MOODLE_SESSION_COOKIE=\"MoodleSession=fresh\"" in (tmp_path / ".env").read_text()


@pytest.mark.asyncio
@respx.mock
async def test_moodle_transport_never_sends_moodle_cookie_to_id_vut_cz() -> None:
    settings = _settings(moodle_session_cookie="MoodleSession=keep")
    seen_headers: list[str | None] = []
    respx.get("https://moodle.vut.cz/my/").mock(
        return_value=httpx.Response(302, headers={"location": "https://id.vut.cz/auth/common/"})
    )
    respx.get("https://id.vut.cz/auth/common/").mock(
        side_effect=lambda request: seen_headers.append(request.headers.get("cookie"))
        or httpx.Response(200, html="<input name=login>")
    )

    with pytest.raises(MoodleAuthError):
        await MoodleTransport(settings).get_response("/my/")

    assert seen_headers == [None]
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_moodle_auth.py tests/test_moodle_transport.py -q`

Expected: FAIL because `MoodleTransport` and `refresh_moodle_session_cookie` are missing.

- [ ] **Step 3: Implement Moodle authentication and transport**

```python
MOODLE_LOGIN_PATH = "/auth/oidc/?source=loginpage"


async def refresh_moodle_session_cookie(settings: Settings) -> str:
    entry_url = urljoin(str(settings.moodle_base_url), MOODLE_LOGIN_PATH)
    result = await login_via_vut_sso(
        settings,
        entry_url=entry_url,
        target_origin=str(settings.moodle_base_url),
        authenticated=_looks_like_moodle_home,
    )
    if not result.authenticated or not result.session_cookie:
        raise MoodleAuthError("Login did not produce an authenticated Moodle session.")
    return result.session_cookie
```

`MoodleTransport` must use the same safety properties as the repaired `StudisTransport`: resolve request URLs against `moodle_base_url`, reject every non-identical origin, build secure host-only cookies, strip cookies on an off-origin redirect, persist only same-origin `Set-Cookie` responses, and retry a login page once. It writes only `VUT_MOODLE_SESSION_COOKIE`; it must never alter `VUT_SESSION_COOKIE`.

Treat either `/login/index.php` on Moodle or a final `id.vut.cz` URL as a Moodle login response. A normal 2xx page on `moodle.vut.cz` that is neither login form is authenticated.

- [ ] **Step 4: Run focused transport tests**

Run: `uv run pytest tests/test_moodle_auth.py tests/test_moodle_transport.py -q`

Expected: PASS.

- [ ] **Step 5: Commit secure Moodle session handling**

```bash
git add src/vut_moodle tests/test_moodle_auth.py tests/test_moodle_transport.py
git commit -m "feat: add Moodle session transport"
```

### Task 5: Implement the optional REST adapter and its strict failure modes

**Files:**
- Create: `src/vut_moodle/api.py`
- Modify: `src/vut_moodle/client.py`
- Test: `tests/test_moodle_client.py`

- [ ] **Step 1: Add REST adapter tests with redacted fixture payloads**

```python
@pytest.mark.asyncio
@respx.mock
async def test_api_mode_returns_courses_and_assignments() -> None:
    settings = _settings(moodle_access_mode="api", moodle_token="test-token")
    respx.post("https://moodle.vut.cz/webservice/rest/server.php").mock(
        side_effect=[courses_response, contents_response, assignments_response]
    )

    client = MoodleClient(settings)

    assert [course.name for course in await client.get_courses()] == ["Algorithms"]
    assert (await client.get_assignments())[0].due_at == datetime(2026, 7, 14, 21, 59, tzinfo=UTC)


@pytest.mark.asyncio
async def test_api_mode_requires_an_explicit_token() -> None:
    with pytest.raises(MoodleConfigurationError, match="VUT_MOODLE_TOKEN"):
        await MoodleClient(_settings(moodle_access_mode="api")).get_courses()
```

- [ ] **Step 2: Run focused client tests and verify failure**

Run: `uv run pytest tests/test_moodle_client.py -q`

Expected: FAIL because `MoodleClient` does not exist.

- [ ] **Step 3: Implement a constrained REST caller**

```python
class MoodleApi:
    async def call(self, function: str, **params: object) -> dict[str, object]:
        response = await self.client.post(
            "/webservice/rest/server.php",
            data={
                "wstoken": self.token,
                "wsfunction": function,
                "moodlewsrestformat": "json",
                **flatten_moodle_params(params),
            },
        )
        payload = response.json()
        if "exception" in payload:
            raise MoodleApiError(function, str(payload.get("message") or payload["exception"]))
        return cast(dict[str, object], payload)
```

Implement only these reads: `core_webservice_get_site_info`, `core_enrol_get_users_courses`, `core_course_get_contents`, and `mod_assign_get_assignments`. Convert URLs to absolute URLs under `moodle_base_url`; reject a returned file URL whose origin differs from Moodle. Represent an API function missing/forbidden error as `MoodleApiError` with the function name, never silently return an empty list.

- [ ] **Step 4: Run REST-mode tests**

Run: `uv run pytest tests/test_moodle_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the opt-in API adapter**

```bash
git add src/vut_moodle/api.py src/vut_moodle/client.py tests/test_moodle_client.py
git commit -m "feat: add optional Moodle REST adapter"
```

### Task 6: Implement the authenticated web fallback and parsers

**Files:**
- Create: `src/vut_moodle/parsers.py`
- Modify: `src/vut_moodle/client.py`
- Test: `tests/test_moodle_parsers.py`
- Test: `tests/test_moodle_client.py`

- [ ] **Step 1: Write parser tests using only anonymous data**

```python
def test_parse_dashboard_courses_uses_course_view_ids() -> None:
    courses = parse_dashboard_courses(
        '<a href="/course/view.php?id=42">Algorithms</a>',
        base_url="https://moodle.vut.cz/my/",
    )

    assert courses == [MoodleCourse(id=42, name="Algorithms", url="https://moodle.vut.cz/course/view.php?id=42")]


def test_parse_assignment_page_extracts_deadline_and_attachment_metadata() -> None:
    assignment = parse_assignment_page(ANONYMIZED_ASSIGNMENT_HTML, base_url="https://moodle.vut.cz/mod/assign/view.php?id=17", course_id=42)

    assert assignment.name == "Project 1"
    assert assignment.due_at == datetime(2026, 7, 14, 21, 59, tzinfo=UTC)
    assert assignment.files[0].name == "specification.pdf"
```

- [ ] **Step 2: Run parser tests and verify failure**

Run: `uv run pytest tests/test_moodle_parsers.py -q`

Expected: FAIL because parser functions are missing.

- [ ] **Step 3: Implement narrow, link-based parsers**

```python
def parse_dashboard_courses(html: str, *, base_url: str) -> list[MoodleCourse]:
    courses: list[MoodleCourse] = []
    seen_ids: set[int] = set()
    for node in HTMLParser(html).css("a"):
        url = urljoin(base_url, node.attributes.get("href") or "")
        parsed = urlparse(url)
        course_id = parse_positive_query_id(parsed, path="/course/view.php")
        if course_id is None or course_id in seen_ids:
            continue
        name = node.text(strip=True)
        if name:
            courses.append(MoodleCourse(id=course_id, name=name, url=url))
            seen_ids.add(course_id)
    return courses


def parse_course_assignments(html: str, *, base_url: str, course: MoodleCourse) -> list[tuple[int, str]]:
    assignments: list[tuple[int, str]] = []
    for node in HTMLParser(html).css("a"):
        url = urljoin(base_url, node.attributes.get("href") or "")
        assignment_id = parse_positive_query_id(urlparse(url), path="/mod/assign/view.php")
        name = node.text(strip=True)
        if assignment_id is not None and name:
            assignments.append((assignment_id, url))
    return assignments


def parse_assignment_page(
    html: str, *, base_url: str, course_id: int, course_name: str | None = None,
) -> MoodleAssignment:
    tree = HTMLParser(html)
    assignment_id = parse_positive_query_id(urlparse(base_url), path="/mod/assign/view.php")
    if assignment_id is None:
        raise MoodleDataError("Moodle assignment URL is missing its id query parameter.")
    heading = tree.css_first("h1")
    if heading is None or not heading.text(strip=True):
        raise MoodleDataError("Moodle assignment page has no heading.")
    files = parse_pluginfile_links(tree, base_url=base_url)
    return MoodleAssignment(
        id=assignment_id, course_id=course_id, course_name=course_name,
        name=heading.text(strip=True), url=base_url,
        due_at=parse_moodle_due_date(tree), files=files,
    )
```

```python
def parse_positive_query_id(parsed: ParseResult, *, path: str) -> int | None:
    if parsed.path != path:
        return None
    value = parse_qs(parsed.query).get("id", [""])[0]
    return int(value) if value.isdecimal() and int(value) > 0 else None


def parse_pluginfile_links(tree: HTMLParser, *, base_url: str) -> list[MoodleFile]:
    files: list[MoodleFile] = []
    for node in tree.css("a"):
        url = urljoin(base_url, node.attributes.get("href") or "")
        if urlparse(url).path.startswith("/pluginfile.php/") and node.text(strip=True):
            files.append(MoodleFile(name=node.text(strip=True), url=url))
    return files


def parse_moodle_due_date(tree: HTMLParser) -> datetime | None:
    node = tree.css_first("time[data-timestamp]")
    return datetime.fromtimestamp(int(node.attributes["data-timestamp"]), UTC) if node else None
```

The fallback flow is: GET `/my/` -> parse course IDs -> GET each `/course/view.php?id={id}` -> parse assignment activity IDs -> GET each `/mod/assign/view.php?id={id}`. Limit a single refresh to 50 courses and 200 assignments; when a limit would be exceeded, raise `MoodleDataError` with the limit rather than making unbounded requests.

- [ ] **Step 4: Add mode-selection tests and implement it**

```python
async def _use_api(self) -> bool:
    return self.settings.moodle_access_mode == "api" or (
        self.settings.moodle_access_mode == "auto" and bool(self.settings.moodle_token)
    )
```

In `auto` mode, a missing/forbidden API function must fall back to web mode only after emitting a single `MoodleApiError`-free internal decision; in explicit `api` mode it must propagate `MoodleApiError`. Explicit `web` mode must not instantiate `MoodleApi`.

- [ ] **Step 5: Run parser and client tests**

Run: `uv run pytest tests/test_moodle_parsers.py tests/test_moodle_client.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the working fallback**

```bash
git add src/vut_moodle/parsers.py src/vut_moodle/client.py tests/test_moodle_parsers.py tests/test_moodle_client.py
git commit -m "feat: add Moodle web fallback"
```

### Task 7: Add cache keys and standalone MCP tools

**Files:**
- Modify: `src/vut_moodle/client.py`
- Modify: `src/vut_mcp/context.py`
- Modify: `src/vut_mcp/server.py`
- Test: `tests/test_moodle_client.py`
- Test: `tests/test_mcp_context.py`
- Test: `tests/test_mcp_payloads.py`

- [ ] **Step 1: Add cache and MCP behavior tests**

```python
@pytest.mark.asyncio
async def test_moodle_courses_are_cached_by_source_and_mode(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(cache_path=tmp_path / "cache.sqlite3", moodle_access_mode="web")
    client = MoodleClient(settings)
    calls = 0

    async def fetch_courses() -> list[MoodleCourse]:
        nonlocal calls
        calls += 1
        return [MoodleCourse(id=1, name="Algorithms", url="https://moodle.vut.cz/course/view.php?id=1")]

    monkeypatch.setattr(client, "_fetch_courses_web", fetch_courses)
    assert await client.get_courses() == await client.get_courses()
    assert calls == 1


def test_moodle_mcp_tools_return_json_serializable_models() -> None:
    result = asyncio.run(vut_get_moodle_assignments(force_refresh=False))

    assert json.loads(json.dumps([item.model_dump(mode="json") for item in result]))
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/test_mcp_context.py tests/test_mcp_payloads.py tests/test_moodle_client.py -q`

Expected: FAIL because the Moodle context getter and MCP tools are missing.

- [ ] **Step 3: Add cache-backed public methods and MCP tools**

```python
def get_moodle_client() -> MoodleClient:
    return MoodleClient()
```

```python
@mcp.tool()
async def vut_get_moodle_courses(force_refresh: bool = False):
    """List courses available to the student in VUT Moodle."""
    return await get_moodle_client().get_courses(force_refresh=force_refresh)


@mcp.tool()
async def vut_get_moodle_assignments(
    course_id: int | None = None,
    force_refresh: bool = False,
):
    """List Moodle assignment deadlines and submission states; read-only."""
    return await get_moodle_client().get_assignments(course_id=course_id, force_refresh=force_refresh)


@mcp.tool()
async def vut_get_moodle_assignment_files(
    assignment_id: int,
    force_refresh: bool = False,
):
    """List metadata and Moodle URLs for assignment attachments; never downloads file bytes."""
    return await get_moodle_client().get_assignment_files(assignment_id, force_refresh=force_refresh)
```

Use cache resource types `moodle_courses`, `moodle_assignments`, and `moodle_assignment_files`; include the normalized access mode in every key. Use a 15-minute TTL for courses, 5 minutes for assignments, and 60 minutes for file metadata.

- [ ] **Step 4: Run focused integration tests**

Run: `uv run pytest tests/test_mcp_context.py tests/test_mcp_payloads.py tests/test_moodle_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit MCP exposure**

```bash
git add src/vut_moodle src/vut_mcp/context.py src/vut_mcp/server.py tests/test_mcp_context.py tests/test_mcp_payloads.py tests/test_moodle_client.py
git commit -m "feat: expose Moodle courses and assignments"
```

### Task 8: Document configuration and run a real read-only verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Test: `tests/test_imports.py`

- [ ] **Step 1: Add documentation assertions/coverage where applicable**

```python
def test_moodle_client_is_publicly_importable() -> None:
    from vut_moodle import MoodleClient

    assert MoodleClient.__name__ == "MoodleClient"
```

- [ ] **Step 2: Document exact safe setup**

Add this configuration block without actual secret values:

```env
VUT_MOODLE_BASE_URL=https://moodle.vut.cz
VUT_MOODLE_ACCESS_MODE=auto
VUT_MOODLE_TOKEN=
VUT_MOODLE_SESSION_COOKIE=
```

Explain: the client reuses `VUT_USERNAME`/`VUT_PASSWORD` only to obtain a Moodle session through VUT SSO; `VUT_MOODLE_SESSION_COOKIE` is distinct from `VUT_SESSION_COOKIE`; `VUT_MOODLE_TOKEN` is optional and must be user-provided; no token is auto-created; and the three tools return metadata/links only.

- [ ] **Step 3: Run full automated validation**

Run: `uv run pytest -q && uv run ruff check . && git diff --check`

Expected: all tests pass, Ruff reports `All checks passed!`, and `git diff --check` produces no output.

- [ ] **Step 4: Run one live, metadata-only smoke test with local credentials**

Run: `uv run vut-studis-debug moodle-assignments --live`

Expected: an anonymized-on-screen list of assignment names/deadlines/URLs, or a clear `MoodleApiError` followed by successful web fallback in `auto` mode. Confirm the command does not write `VUT_MOODLE_TOKEN`, does not submit anything, and does not print cookie values.

- [ ] **Step 5: Commit documentation and finish**

```bash
git add README.md .env.example tests/test_imports.py
git commit -m "docs: explain Moodle integration setup"
```

## Plan self-review

- **Spec coverage:** courses, deadlines, file metadata, API option, SSO, cookie isolation, caching, MCP tools, documentation, and real read-only validation are covered in Tasks 2–8. Binary downloads, file indexing, submissions, Raycast, notifications, and daily-briefing merging are intentionally excluded by the MVP contract.
- **Technical uncertainty:** API endpoint existence and SSO are verified; the site's enabled student functions remain unknown. Task 5 makes that uncertainty explicit and Task 6 supplies a tested web fallback.
- **Security:** every task preserves exact-origin cookie restrictions, isolates Moodle configuration from Studis, avoids automatic token creation, and keeps fixtures anonymized.
- **Repository health:** Task 1 repairs the present syntax error before tests/imports are relied upon.
