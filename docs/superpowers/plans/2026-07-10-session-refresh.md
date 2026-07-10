# Studis Session Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make password relogin produce a Studis-scoped session, preserve cookie rotation across requests, and retry an expired request exactly once.

**Architecture:** Keep `vut_studis.auth` responsible for the SSO flow and cookie-scope projection, and keep `vut_studis.transport` responsible for applying/persisting the Studis session and the one-retry policy. Persist the existing `VUT_SESSION_COOKIE` format for compatibility, but derive it through the standard cookie jar for the target Studis URL instead of flattening cookies from every SSO domain.

**Tech Stack:** Python 3.12, `httpx`, stdlib `http.cookiejar`/`http.cookies`/`urllib`, `pytest`, `respx`, Ruff

---

## Diagnosis and boundaries

- The current suite passes (`48 passed`) and Ruff is clean, so existing tests do not model the failure.
- The live anonymous login inspection still reaches `id.vut.cz/auth/common/...` and exposes the expected `login` form. Do not change the username/password form sequence without a failing reproduction.
- `auth._cookie_header()` currently iterates the complete cookie jar. That loses domain/path applicability and writes SSO cookies for `id.vut.cz` into the header later sent to `www.vut.cz`.
- The current local header contains five cookie entries, including duplicate `_nss` names. Values were not inspected. Duplicate names are consistent with scoped cookies being flattened.
- `StudisTransport` creates a new HTTP client for each request with a literal `Cookie` header. It therefore discards `Set-Cookie` updates received from authenticated Studis responses.
- Keep the MCP layer unchanged and read-only. Do not add background refresh, proactive expiry prediction, or cross-process locking in this fix. Add locking later only if duplicate concurrent logins can be reproduced after cookie handling is correct.

## File map

- Modify `src/vut_studis/auth.py`: classify login responses consistently and project a cookie jar to a target URL.
- Modify `src/vut_studis/transport.py`: seed an HTTP cookie jar from the saved Studis header, retain response cookie updates, persist changes, and keep a single retry.
- Modify `tests/test_auth.py`: model the current cross-host SSO flow and verify domain/path filtering and false-positive authentication prevention.
- Modify `tests/test_client_auth_retry.py`: verify refresh request headers, response cookie rotation, persistence, and the retry ceiling.
- Modify `README.md`: document automatic refresh and cookie rotation behavior.

### Task 1: Make authentication classification and cookie export URL-aware

**Files:**
- Modify: `src/vut_studis/auth.py:1-12`
- Modify: `src/vut_studis/auth.py:49-54`
- Modify: `src/vut_studis/auth.py:142-190`
- Modify: `src/vut_studis/auth.py:256-266`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write failing focused tests for login classification and cookie scoping**

Add the new imports and tests below to `tests/test_auth.py`. The cookie test deliberately places same-purpose cookies on the identity and Studis hosts so the old jar-flattening behavior fails.

```python
from vut_studis.auth import (
    _cookie_header_for_url,
    _looks_authenticated,
    inspect_login_flow,
    is_login_response,
    login_with_password,
    refresh_session_cookie,
)


def test_cookie_header_for_url_excludes_identity_provider_cookies() -> None:
    cookies = httpx.Cookies()
    cookies.set("nosec_sess", "id-only", domain="id.vut.cz", path="/")
    cookies.set("_nss", "id-csrf", domain="id.vut.cz", path="/")
    cookies.set("VUTSESSIONID", "studis", domain="www.vut.cz", path="/")
    cookies.set("PHPSESSID", "php", domain="www.vut.cz", path="/studis")

    header = _cookie_header_for_url(
        cookies.jar,
        "https://www.vut.cz/studis/student.phtml?sn=el_index",
    )

    assert header == "PHPSESSID=php; VUTSESSIONID=studis"


def test_is_login_response_uses_final_auth_url() -> None:
    response = httpx.Response(
        200,
        request=httpx.Request(
            "GET",
            "https://id.vut.cz/auth/common/oauth2/authorize?client_id=studis",
        ),
        html="<title>Sign in</title>",
    )

    assert is_login_response(response) is True


def test_studis_url_with_login_page_is_not_authenticated() -> None:
    response = httpx.Response(
        200,
        request=httpx.Request(
            "GET",
            "https://www.vut.cz/studis/student.phtml?sn=el_index",
        ),
        html="<title>Jednotné přihlášení VUT</title>",
    )

    assert _looks_authenticated(response) is False
```

- [ ] **Step 2: Run the new tests and verify the current implementation fails**

Run:

```bash
uv run pytest \
  tests/test_auth.py::test_cookie_header_for_url_excludes_identity_provider_cookies \
  tests/test_auth.py::test_is_login_response_uses_final_auth_url \
  tests/test_auth.py::test_studis_url_with_login_page_is_not_authenticated -q
```

Expected: collection/import failure because `_cookie_header_for_url` and `is_login_response` do not exist yet; after importing only existing symbols, the authentication false-positive test should fail.

- [ ] **Step 3: Implement target-URL cookie projection and shared response classification**

In `src/vut_studis/auth.py`, add `Request` to the urllib imports:

```python
from urllib.parse import urljoin
from urllib.request import Request
```

Replace the final cookie export in `login_with_password()`:

```python
    return LoginAttemptResult(
        final_url=str(final_response.url),
        status_code=final_response.status_code,
        authenticated=_looks_authenticated(final_response),
        cookie_names=sorted(cookie.name for cookie in client.cookies.jar),
        session_cookie=_cookie_header_for_url(client.cookies.jar, entry_url),
        title=_parse_title(final_response.text),
    )
```

Replace `_looks_authenticated()` and `_cookie_header()` with these functions:

```python
def is_login_response(response: httpx.Response) -> bool:
    url = str(response.url).casefold()
    title = (_parse_title(response.text) or "").casefold()
    return "/auth/common/" in url or "jednotné přihlášení vut" in title


def _looks_authenticated(response: httpx.Response) -> bool:
    if is_login_response(response):
        return False

    final_url = str(response.url).casefold()
    if "/studis/" in final_url and "student.phtml" in final_url:
        return True

    title = (_parse_title(response.text) or "").casefold()
    return "studis" in title


def _cookie_header_for_url(cookie_jar: CookieJar, url: str) -> str:
    request = Request(url)
    cookie_jar.add_cookie_header(request)
    return request.get_header("Cookie") or ""
```

Strengthen `refresh_session_cookie()` so a URL false positive cannot persist an empty session:

```python
async def refresh_session_cookie(settings: Settings | None = None) -> str:
    result = await login_with_password(settings)
    if not result.authenticated or not result.session_cookie:
        raise StudisAuthError("Login did not produce an authenticated Studis session.")

    return result.session_cookie
```

- [ ] **Step 4: Update the cross-host login fixture to resemble the live flow**

In `tests/test_auth.py`, replace `META_HOME_REFRESH` and the mock URLs used by `test_login_with_password_returns_session_cookie()` so the SSO cookies are set on `id.vut.cz` and the Studis cookies are set on `www.vut.cz`:

```python
META_HOME_REFRESH = (
    '<meta http-equiv="refresh" '
    'content="0; url=https://id.vut.cz/auth/common/home/default?authSectionId=abc">'
)


@pytest.mark.asyncio
@respx.mock
async def test_login_with_password_returns_studis_scoped_session_cookie() -> None:
    captured_password_payload: dict[str, list[str]] = {}

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=[
            httpx.Response(200, html=META_HOME_REFRESH),
            httpx.Response(
                200,
                headers=[
                    ("set-cookie", "VUTSESSIONID=session-value; Path=/"),
                    ("set-cookie", "PHPSESSID=php-value; Path=/studis"),
                ],
                html="<title>Elektronický index</title>",
            ),
        ]
    )
    respx.get("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <form method="post" action="/auth/common/home/default?authSectionId=abc">
              <input type="text" name="login">
              <input type="hidden" name="_token_" value="username-token">
              <input type="hidden" name="_do" value="signInForm-submit">
            </form>
            """,
        )
    )
    respx.post("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <form method="post" action="/auth/common/password/default?authSectionId=abc">
              <input type="password" name="passwd">
              <input type="hidden" name="_token_" value="password-token">
              <input type="hidden" name="fingerprintData">
              <input type="hidden" name="_do" value="signInFormPassword-submit">
            </form>
            """,
        )
    )

    def password_submit(request: httpx.Request) -> httpx.Response:
        captured_password_payload.update(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            headers={"set-cookie": "nosec_sess=id-only; Path=/"},
            html=(
                '<meta http-equiv="refresh" '
                'content="0; url=https://www.vut.cz/studis/student.phtml?sn=el_index">'
            ),
        )

    respx.post("https://id.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        side_effect=password_submit
    )

    result = await login_with_password(_settings())

    assert result.authenticated is True
    assert result.final_url == "https://www.vut.cz/studis/student.phtml?sn=el_index"
    assert result.session_cookie == "PHPSESSID=php-value; VUTSESSIONID=session-value"
    assert "nosec_sess" in result.cookie_names
    assert "nosec_sess" not in result.session_cookie
    assert captured_password_payload["passwd"] == ["secret"]
    assert "fingerprintData" in captured_password_payload
```

Update the existing failure assertion to match the strengthened error:

```python
    with pytest.raises(StudisAuthError, match="authenticated Studis session"):
        await refresh_session_cookie(_settings())
```

- [ ] **Step 5: Run the auth tests**

Run: `uv run pytest tests/test_auth.py -q`

Expected: all auth tests pass.

- [ ] **Step 6: Commit the auth fix**

```bash
git add src/vut_studis/auth.py tests/test_auth.py
git commit -m "fix: scope refreshed cookies to Studis"
```

### Task 2: Preserve Studis cookie rotation in the transport

**Files:**
- Modify: `src/vut_studis/transport.py:1-83`
- Test: `tests/test_client_auth_retry.py`

- [ ] **Step 1: Write a failing test for an authenticated response that rotates the session**

Add these imports to `tests/test_client_auth_retry.py`:

```python
from pathlib import Path

from vut_studis.transport import StudisTransport
```

Add the test:

```python
@pytest.mark.asyncio
@respx.mock
async def test_authenticated_response_persists_rotated_cookie(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('VUT_SESSION_COOKIE="VUTSESSIONID=old"\n')
    settings = _settings("VUTSESSIONID=old")
    seen_cookie_headers: list[str] = []

    def first_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(
            200,
            headers={"set-cookie": "VUTSESSIONID=rotated; Path=/"},
            html="<title>Elektronický index</title>",
        )

    def second_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(200, html="<title>Elektronický index</title>")

    route = respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=[first_response, second_response]
    )
    transport = StudisTransport(settings, env_path=env_path)

    await transport.get_html("/studis/student.phtml?sn=el_index")
    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert route.call_count == 2
    assert seen_cookie_headers == ["VUTSESSIONID=old", "VUTSESSIONID=rotated"]
    assert settings.session_cookie == "VUTSESSIONID=rotated"
    assert 'VUT_SESSION_COOKIE="VUTSESSIONID=rotated"' in env_path.read_text()
```

- [ ] **Step 2: Run the rotation test and verify it fails**

Run:

```bash
uv run pytest \
  tests/test_client_auth_retry.py::test_authenticated_response_persists_rotated_cookie -q
```

Expected: FAIL because the second request still sends `VUTSESSIONID=old` and neither settings nor `.env` is updated.

- [ ] **Step 3: Seed HTTPX with cookies and persist changes from authenticated responses**

Update the imports in `src/vut_studis/transport.py`:

```python
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from vut_studis.auth import (
    _cookie_header_for_url,
    is_login_response,
    refresh_session_cookie,
)
```

Because `META_HOME_REFRESH` is shared, change every mocked username/password route in `tests/test_auth.py` from `https://www.vut.cz/auth/common/...` to the same `https://id.vut.cz/auth/common/...` path. This includes `test_inspect_login_flow_follows_meta_refresh()` and `test_refresh_session_cookie_requires_authenticated_result()`; their response bodies and assertions remain unchanged.

Replace `_request_authenticated()`, `_headers()`, `_http_client()`, and `_is_login_response()` with:

```python
    async def _request_authenticated(self, path: str) -> httpx.Response | None:
        requested_url = urljoin(str(self.settings.base_url), path)
        async with self._http_client() as client:
            response = await client.get(path)
            response.raise_for_status()
            if is_login_response(response):
                return None

            self._persist_cookie_jar(client.cookies, requested_url)
            return response

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=str(self.settings.base_url),
            follow_redirects=True,
            timeout=self.settings.http_timeout_seconds,
            cookies=self._session_cookies(),
        )

    def _session_cookies(self) -> httpx.Cookies:
        if not self.settings.session_cookie:
            raise StudisAuthError("VUT_SESSION_COOKIE is not configured.")

        host = urlparse(str(self.settings.base_url)).hostname
        if host is None:
            raise StudisAuthError("VUT_BASE_URL does not contain a hostname.")

        parsed = SimpleCookie()
        parsed.load(self.settings.session_cookie)
        cookies = httpx.Cookies()
        for morsel in parsed.values():
            cookies.set(morsel.key, morsel.value, domain=host, path="/")
        return cookies

    def _persist_cookie_jar(self, cookies: httpx.Cookies, requested_url: str) -> None:
        session_cookie = _cookie_header_for_url(cookies.jar, requested_url)
        if not session_cookie or session_cookie == self.settings.session_cookie:
            return

        set_env_value(self.env_path, "VUT_SESSION_COOKIE", session_cookie)
        self.settings.session_cookie = session_cookie
```

Keep `_refresh_session_cookie()` as the path that persists a full password relogin result. The response-persistence helper must run only after `is_login_response()` returns false, so cookies from the identity provider never overwrite the Studis session.

- [ ] **Step 4: Strengthen the refresh test to assert the cookie used for the retry**

In `test_get_html_refreshes_expired_session_and_retries()`, capture the cookie headers for only the original protected request and its retry:

```python
    protected_request_cookies: list[str] = []
    studis_call_count = 0

    def studis_response(request: httpx.Request) -> httpx.Response:
        nonlocal studis_call_count
        studis_call_count += 1
        if studis_call_count == 1:
            protected_request_cookies.append(request.headers["cookie"])
            return httpx.Response(200, html="<title>Jednotné přihlášení VUT</title>")
        if studis_call_count == 2:
            return httpx.Response(200, html=META_HOME_REFRESH)
        if studis_call_count == 3:
            return httpx.Response(
                200,
                headers={"set-cookie": "VUTSESSIONID=fresh-session; Path=/"},
                html="<title>Elektronický index</title>",
            )

        protected_request_cookies.append(request.headers["cookie"])
        return httpx.Response(200, html="<title>Retried Studis page</title>")

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=studis_response
    )
```

Add this assertion after the request:

```python
    assert protected_request_cookies == ["expired=session", "VUTSESSIONID=fresh-session"]
```

When adapting the fixture to the cross-host SSO constant from Task 1, use `id.vut.cz` for the username/password routes and make the final Studis response set `VUTSESSIONID=fresh-session`. Do not assert the full SSO jar.

Use this absolute meta-refresh constant at the top of `tests/test_client_auth_retry.py`:

```python
META_HOME_REFRESH = (
    '<meta http-equiv="refresh" '
    'content="0; url=https://id.vut.cz/auth/common/home/default?authSectionId=abc">'
)
```

Change both authentication routes in the refresh test to `id.vut.cz`:

```python
respx.get("https://id.vut.cz/auth/common/home/default?authSectionId=abc")
respx.post("https://id.vut.cz/auth/common/home/default?authSectionId=abc")
respx.post("https://id.vut.cz/auth/common/password/default?authSectionId=abc")
```

- [ ] **Step 5: Add a retry-ceiling regression test**

Add:

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_html_refreshes_only_once_when_retry_is_login_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def fake_refresh_session_cookie(settings: Settings) -> str:
        return "VUTSESSIONID=fresh-session"

    monkeypatch.setattr(
        "vut_studis.transport.refresh_session_cookie",
        fake_refresh_session_cookie,
    )
    route = respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(200, html="<title>Jednotné přihlášení VUT</title>")
    )
    settings = _settings()
    client = StudisClient(
        settings,
        transport=StudisTransport(settings, env_path=tmp_path / ".env"),
    )

    with pytest.raises(StudisAuthError, match="retry was not authenticated"):
        await client._get_html("/studis/student.phtml?sn=el_index")

    assert route.call_count == 2
```

- [ ] **Step 6: Run transport and auth tests**

Run:

```bash
uv run pytest tests/test_auth.py tests/test_client_auth_retry.py tests/test_mcp_context.py -q
```

Expected: all targeted tests pass. The MCP context test must continue proving that callers receive fresh `StudisClient` instances; cookie correctness belongs below that layer.

- [ ] **Step 7: Commit the transport fix**

```bash
git add src/vut_studis/transport.py tests/test_client_auth_retry.py
git commit -m "fix: retain Studis session cookie rotation"
```

### Task 3: Document behavior and run final validation

**Files:**
- Modify: `README.md:43-52`

- [ ] **Step 1: Update the session documentation**

Replace the paragraph after `login-refresh-session` with:

```markdown
The command updates `VUT_SESSION_COOKIE` in `.env`. Studis sessions expire, so
the client uses `VUT_USERNAME` and `VUT_PASSWORD` to log in again and retries the
failed request once. Only cookies applicable to the Studis URL are persisted;
cookies returned by Studis during normal requests are carried forward
automatically. You can still run the command manually to force a new session.
```

- [ ] **Step 2: Run the complete automated checks**

Run:

```bash
uv run ruff check .
uv run pytest
```

Expected: Ruff exits successfully and all tests pass.

- [ ] **Step 3: Run the sanitized live login inspection**

Run:

```bash
uv run vut-studis-debug login-inspect
```

Expected: the inspection reaches an `id.vut.cz/auth/common/...` page and reports a form containing `login`. This command must not submit credentials or print cookie values.

- [ ] **Step 4: Manually verify relogin without exposing secrets**

Run the existing sanitized command:

```bash
uv run vut-studis-debug login-refresh-session
```

Expected: output reports `authenticated: true`, lists cookie names only, and updates `.env`. Then run:

```bash
uv run vut-studis-debug grades
```

Expected: grades load successfully without another password relogin. Do not paste `.env`, raw cookies, Studis HTML, or student data into test fixtures or logs.

- [ ] **Step 5: Commit documentation**

```bash
git add README.md
git commit -m "docs: clarify Studis session refresh"
```

## Self-review

- Spec coverage: the plan covers expired-session detection, one refresh, one retry, scoped cookie persistence, normal response rotation, fresh MCP clients, sanitized live verification, and documentation.
- Deliberate non-goals: no MCP orchestration changes, no proactive scheduler, no credential storage changes, no multi-process file lock, and no real Studis fixtures.
- Type consistency: cookie projection accepts `CookieJar`; both `httpx.AsyncClient.cookies.jar` and the auth login client's jar satisfy that interface. The persisted compatibility type remains `str` in `Settings.session_cookie` and `LoginAttemptResult.session_cookie`.
