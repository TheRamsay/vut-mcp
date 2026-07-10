from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from vut_studis.client import StudisClient
from vut_studis.config import Settings
from vut_studis.errors import StudisAuthError
from vut_studis.transport import StudisTransport

META_HOME_REFRESH = (
    '<meta http-equiv="refresh" '
    'content="0; url=https://id.vut.cz/auth/common/home/default?authSectionId=abc">'
)


def _settings(session_cookie: str | None = "expired=session") -> Settings:
    return Settings(
        VUT_BASE_URL="https://www.vut.cz",
        VUT_USERNAME="test-user",
        VUT_PASSWORD="secret",
        VUT_SESSION_COOKIE=session_cookie,
        VUT_CACHE_DISABLED=True,
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_html_refreshes_expired_session_and_retries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("vut_studis.transport.ENV_PATH", tmp_path / ".env")
    captured_password_payload: dict[str, list[str]] = {}
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
    respx.get("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <form method="post" action="/auth/common/home/default?authSectionId=abc">
              <input type="text" name="login">
              <input type="hidden" name="_token_" value="username-token">
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
            </form>
            """,
        )
    )

    def password_submit(request: httpx.Request) -> httpx.Response:
        captured_password_payload.update(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            html=(
                '<meta http-equiv="refresh" '
                'content="0; url=https://www.vut.cz/studis/student.phtml?sn=el_index">'
            ),
        )

    respx.post("https://id.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        side_effect=password_submit
    )

    client = StudisClient(_settings())
    html = await client._get_html("/studis/student.phtml?sn=el_index")

    assert "Retried Studis page" in html
    assert client.settings.session_cookie == "VUTSESSIONID=fresh-session"
    assert 'VUT_SESSION_COOKIE="VUTSESSIONID=fresh-session"' in (tmp_path / ".env").read_text()
    assert captured_password_payload["passwd"] == ["secret"]
    assert protected_request_cookies == ["expired=session", "VUTSESSIONID=fresh-session"]


@pytest.mark.asyncio
@respx.mock
async def test_authenticated_response_persists_rotated_cookie(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('VUT_SESSION_COOKIE="VUTSESSIONID=old; PHPSESSID=keep"\n')
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
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
    assert seen_cookie_headers == [
        "VUTSESSIONID=old; PHPSESSID=keep",
        "VUTSESSIONID=rotated; PHPSESSID=keep",
    ]
    assert settings.session_cookie == "VUTSESSIONID=rotated; PHPSESSID=keep"
    assert (
        'VUT_SESSION_COOKIE="VUTSESSIONID=rotated; PHPSESSID=keep"' in env_path.read_text()
    )


@pytest.mark.asyncio
@respx.mock
async def test_path_specific_rotation_does_not_resurrect_old_cookie(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
    seen_cookie_headers: list[str] = []

    def first_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(
            200,
            headers={"set-cookie": "VUTSESSIONID=path-rotated; Path=/studis"},
            html="<title>Elektronický index</title>",
        )

    def second_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(200, html="<title>Elektronický index</title>")

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=[first_response, second_response]
    )
    transport = StudisTransport(settings, env_path=env_path)

    await transport.get_html("/studis/student.phtml?sn=el_index")
    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert seen_cookie_headers == [
        "VUTSESSIONID=old; PHPSESSID=keep",
        "VUTSESSIONID=path-rotated; PHPSESSID=keep",
    ]
    assert settings.session_cookie == "VUTSESSIONID=path-rotated; PHPSESSID=keep"


@pytest.mark.asyncio
@respx.mock
async def test_same_origin_redirect_retains_all_saved_cookies(tmp_path: Path) -> None:
    seen_cookie_headers: list[str] = []

    def redirect_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(302, headers={"location": "/studis/landing"})

    def final_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(200, html="<title>Elektronický index</title>")

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=redirect_response
    )
    respx.get("https://www.vut.cz/studis/landing").mock(side_effect=final_response)
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
    transport = StudisTransport(settings, env_path=tmp_path / ".env")

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert seen_cookie_headers == [
        "VUTSESSIONID=old; PHPSESSID=keep",
        "VUTSESSIONID=old; PHPSESSID=keep",
    ]
    assert settings.session_cookie == "VUTSESSIONID=old; PHPSESSID=keep"


@pytest.mark.asyncio
@respx.mock
async def test_same_origin_redirect_rotates_one_cookie_and_retains_companion(
    tmp_path: Path,
) -> None:
    seen_cookie_headers: list[str] = []

    def redirect_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(
            302,
            headers={
                "location": "/studis/landing",
                "set-cookie": "VUTSESSIONID=rotated; Path=/",
            },
        )

    def final_response(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(200, html="<title>Elektronický index</title>")

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=redirect_response
    )
    respx.get("https://www.vut.cz/studis/landing").mock(side_effect=final_response)
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
    transport = StudisTransport(settings, env_path=tmp_path / ".env")

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert seen_cookie_headers == [
        "VUTSESSIONID=old; PHPSESSID=keep",
        "VUTSESSIONID=rotated; PHPSESSID=keep",
    ]
    assert settings.session_cookie == "VUTSESSIONID=rotated; PHPSESSID=keep"


@pytest.mark.asyncio
@respx.mock
async def test_authenticated_response_persists_explicit_cookie_deletion(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('VUT_SESSION_COOKIE="VUTSESSIONID=old"\n')
    settings = _settings("VUTSESSIONID=old")
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            headers={
                "set-cookie": (
                    "VUTSESSIONID=; Path=/studis; Max-Age=0; "
                    "Expires=Thu, 01 Jan 1970 00:00:00 GMT"
                )
            },
            html="<title>Elektronický index</title>",
        )
    )
    transport = StudisTransport(settings, env_path=env_path)

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert settings.session_cookie is None
    assert 'VUT_SESSION_COOKIE=""' in env_path.read_text()


@pytest.mark.asyncio
@respx.mock
async def test_later_cookie_set_wins_over_earlier_path_deletion(tmp_path: Path) -> None:
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            headers=[
                ("set-cookie", "VUTSESSIONID=; Path=/studis; Max-Age=0"),
                ("set-cookie", "VUTSESSIONID=reissued; Path=/"),
            ],
            html="<title>Elektronický index</title>",
        )
    )
    transport = StudisTransport(settings, env_path=tmp_path / ".env")

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert settings.session_cookie == "VUTSESSIONID=reissued; PHPSESSID=keep"


@pytest.mark.asyncio
@respx.mock
async def test_path_deletion_does_not_remove_earlier_live_root_set(tmp_path: Path) -> None:
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            headers=[
                ("set-cookie", "VUTSESSIONID=reissued; Path=/"),
                ("set-cookie", "VUTSESSIONID=; Path=/studis; Max-Age=0"),
            ],
            html="<title>Elektronický index</title>",
        )
    )
    transport = StudisTransport(settings, env_path=tmp_path / ".env")

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert settings.session_cookie == "VUTSESSIONID=reissued; PHPSESSID=keep"


@pytest.mark.asyncio
@respx.mock
async def test_unrelated_path_set_does_not_preserve_deleted_session_cookie(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    settings = _settings("VUTSESSIONID=old")
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            headers=[
                ("set-cookie", "VUTSESSIONID=other; Path=/other"),
                ("set-cookie", "VUTSESSIONID=; Path=/studis; Max-Age=0"),
            ],
            html="<title>Elektronický index</title>",
        )
    )
    transport = StudisTransport(settings, env_path=env_path)

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert settings.session_cookie is None
    assert 'VUT_SESSION_COOKIE=""' in env_path.read_text()


@pytest.mark.asyncio
@respx.mock
async def test_later_same_scope_deletion_clears_earlier_set(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    settings = _settings("VUTSESSIONID=old")
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            headers=[
                ("set-cookie", "VUTSESSIONID=reissued; Path=/"),
                ("set-cookie", "VUTSESSIONID=; Path=/; Max-Age=0"),
            ],
            html="<title>Elektronický index</title>",
        )
    )
    transport = StudisTransport(settings, env_path=env_path)

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert settings.session_cookie is None
    assert 'VUT_SESSION_COOKIE=""' in env_path.read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_url",
    [
        pytest.param("https://id.vut.cz/studis/landing", id="cross-host"),
        pytest.param("http://www.vut.cz/studis/landing", id="https-downgrade"),
        pytest.param("https://www.vut.cz:444/studis/landing", id="different-port"),
    ],
)
@respx.mock
async def test_initial_off_origin_absolute_url_is_rejected_without_request(
    tmp_path: Path,
    target_url: str,
) -> None:
    route = respx.get(target_url).mock(
        return_value=httpx.Response(200, html="<title>Elektronický index</title>")
    )
    settings = _settings("VUTSESSIONID=sensitive")
    transport = StudisTransport(settings, env_path=tmp_path / ".env")

    with pytest.raises(StudisAuthError, match="configured base origin"):
        await transport.get_html(target_url)

    assert route.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "redirect_url",
    [
        pytest.param("https://id.vut.cz/landing", id="cross-host"),
        pytest.param("https://portal.www.vut.cz/landing", id="child-host"),
        pytest.param("http://www.vut.cz/landing", id="https-downgrade"),
    ],
)
@respx.mock
async def test_saved_cookie_is_not_forwarded_on_unsafe_redirect(
    tmp_path: Path,
    redirect_url: str,
) -> None:
    source_cookie_headers: list[str | None] = []
    redirected_cookie_headers: list[str | None] = []

    def redirect_response(request: httpx.Request) -> httpx.Response:
        source_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(302, headers={"location": redirect_url})

    def final_response(request: httpx.Request) -> httpx.Response:
        redirected_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(200, html="<title>Elektronický index</title>")

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=redirect_response
    )
    respx.get(redirect_url).mock(side_effect=final_response)
    settings = _settings("VUTSESSIONID=sensitive")
    transport = StudisTransport(settings, env_path=tmp_path / ".env")

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert source_cookie_headers == ["VUTSESSIONID=sensitive"]
    assert redirected_cookie_headers == [None]
    assert settings.session_cookie == "VUTSESSIONID=sensitive"


@pytest.mark.asyncio
@respx.mock
async def test_off_origin_redirect_cookie_cannot_replace_persisted_session(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('VUT_SESSION_COOKIE="VUTSESSIONID=old; PHPSESSID=keep"\n')
    redirected_cookie_headers: list[str | None] = []

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://portal.www.vut.cz/landing"},
        )
    )

    def child_response(request: httpx.Request) -> httpx.Response:
        redirected_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(
            200,
            headers={
                "set-cookie": "VUTSESSIONID=child; Domain=www.vut.cz; Path=/studis"
            },
            html="<title>Elektronický index</title>",
        )

    respx.get("https://portal.www.vut.cz/landing").mock(side_effect=child_response)
    settings = _settings("VUTSESSIONID=old; PHPSESSID=keep")
    transport = StudisTransport(settings, env_path=env_path)

    await transport.get_html("/studis/student.phtml?sn=el_index")

    assert redirected_cookie_headers == [None]
    assert settings.session_cookie == "VUTSESSIONID=old; PHPSESSID=keep"
    assert env_path.read_text() == 'VUT_SESSION_COOKIE="VUTSESSIONID=old; PHPSESSID=keep"\n'


@pytest.mark.asyncio
@respx.mock
async def test_get_html_refreshes_only_once_when_retry_is_login_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    refresh_call_count = 0

    async def fake_refresh_session_cookie(settings: Settings) -> str:
        nonlocal refresh_call_count
        refresh_call_count += 1
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
    assert refresh_call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_html_does_not_refresh_without_credentials() -> None:
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(200, html="<title>Jednotné přihlášení VUT</title>")
    )

    client = StudisClient(
        Settings(
            VUT_BASE_URL="https://www.vut.cz",
            VUT_USERNAME="",
            VUT_PASSWORD="",
            VUT_SESSION_COOKIE="expired=session",
            VUT_CACHE_DISABLED=True,
        )
    )

    with pytest.raises(StudisAuthError, match="session expired"):
        await client._get_html("/studis/student.phtml?sn=el_index")
