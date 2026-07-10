from urllib.parse import parse_qs

import httpx
import pytest
import respx

from vut_studis.auth import (
    LoginAttemptResult,
    _cookie_header_for_url,
    _looks_authenticated,
    _target_form_post,
    inspect_login_flow,
    is_login_response,
    login_via_vut_sso,
    login_with_password,
    refresh_session_cookie,
)
from vut_studis.config import Settings
from vut_studis.errors import StudisAuthError

META_HOME_REFRESH = (
    '<meta http-equiv="refresh" '
    'content="0; url=https://id.vut.cz/auth/common/home/default?authSectionId=abc">'
)


def _settings() -> Settings:
    return Settings(
        VUT_BASE_URL="https://www.vut.cz",
        VUT_USERNAME="test-user",
        VUT_PASSWORD="secret",
    )


@pytest.mark.asyncio
@respx.mock
async def test_login_via_vut_sso_submits_oidc_form_to_moodle() -> None:
    entry_url = "https://moodle.vut.cz/auth/oidc/?source=loginpage"
    respx.get(entry_url).mock(
        return_value=httpx.Response(
            200,
            html=(
                '<meta http-equiv="refresh" '
                'content="0; url=https://id.vut.cz/auth/common/home/default?authSectionId=abc">'
            ),
        )
    )
    respx.get("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html=(
                '<form method="post" action="/auth/common/home/default?authSectionId=abc">'
                '<input name="login"><input name="_token_" value="username-token"></form>'
            ),
        )
    )
    respx.post("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html=(
                '<form method="post" action="/auth/common/password/default?authSectionId=abc">'
                '<input name="passwd"><input name="_token_" value="password-token"></form>'
            ),
        )
    )
    respx.post("https://id.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html=(
                '<form method="post" action="https://moodle.vut.cz/oidc/callback">'
                '<input name="state" value="state-1"><input name="code" value="code-1"></form>'
            ),
        )
    )
    target_route = respx.post("https://moodle.vut.cz/oidc/callback").mock(
        return_value=httpx.Response(
            200,
            headers={"set-cookie": "MoodleSession=moodle-session; Path=/"},
            html="<title>VUT Moodle</title>",
        )
    )

    result = await login_via_vut_sso(
        _settings(),
        entry_url=entry_url,
        target_origin="https://moodle.vut.cz",
        authenticated=lambda response: response.url.path == "/oidc/callback",
    )

    assert result.authenticated is True
    assert result.session_cookie == "MoodleSession=moodle-session"
    assert target_route.call_count == 1
    assert parse_qs(target_route.calls[0].request.content.decode()) == {
        "state": ["state-1"],
        "code": ["code-1"],
    }


def test_target_form_post_rejects_oidc_fields_for_another_origin() -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://id.vut.cz/complete"),
        html=(
            '<form method="post" action="https://evil.example/callback">'
            '<input name="state" value="state-1"><input name="code" value="code-1"></form>'
        ),
    )

    with pytest.raises(StudisAuthError, match="target origin"):
        _target_form_post(response, target_origin="https://moodle.vut.cz")


@pytest.mark.asyncio
@respx.mock
async def test_inspect_login_flow_follows_meta_refresh() -> None:
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            html=f"""
            <title>Jednotné přihlášení VUT</title>
            {META_HOME_REFRESH}
            """,
        )
    )
    respx.get("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <title>Jednotné přihlášení VUT</title>
            <form method="post" action="/auth/common/home/default?authSectionId=abc">
              <input type="text" name="login">
              <input type="hidden" name="_token_" value="token-1">
              <input type="hidden" name="_do" value="signInForm-submit">
            </form>
            """,
        )
    )

    snapshots = await inspect_login_flow(_settings())

    assert len(snapshots) == 2
    assert snapshots[1].forms[0].method == "post"
    assert [field.name for field in snapshots[1].forms[0].fields] == ["login", "_token_", "_do"]


@pytest.mark.asyncio
@respx.mock
async def test_login_with_password_returns_studis_scoped_session_cookie() -> None:
    captured_password_payload: dict[str, list[str]] = {}
    identity_cookie_headers: list[str] = []

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
            headers={"set-cookie": "nosec_sess=id-only; Path=/"},
            html="""
            <form method="post" action="/auth/common/home/default?authSectionId=abc">
              <input type="text" name="login">
              <input type="hidden" name="_token_" value="username-token">
              <input type="hidden" name="_do" value="signInForm-submit">
            </form>
            """,
        )
    )

    def username_submit(request: httpx.Request) -> httpx.Response:
        identity_cookie_headers.append(request.headers["cookie"])
        return httpx.Response(
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

    respx.post("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        side_effect=username_submit
    )

    def password_submit(request: httpx.Request) -> httpx.Response:
        identity_cookie_headers.append(request.headers["cookie"])
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
    result = await login_with_password(_settings())

    assert result.authenticated is True
    assert result.final_url == "https://www.vut.cz/studis/student.phtml?sn=el_index"
    assert result.session_cookie == "PHPSESSID=php-value; VUTSESSIONID=session-value"
    assert "nosec_sess" in result.cookie_names
    assert "nosec_sess" not in result.session_cookie
    assert identity_cookie_headers == ["nosec_sess=id-only", "nosec_sess=id-only"]
    assert captured_password_payload["passwd"] == ["secret"]
    assert "fingerprintData" in captured_password_payload


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


@pytest.mark.parametrize("field_name", ["login", "passwd"])
def test_is_login_response_detects_login_forms_with_localized_title(field_name: str) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request(
            "GET",
            "https://www.vut.cz/studis/student.phtml?sn=el_index",
        ),
        html=f"""
        <title>Anmelden</title>
        <form><input name="{field_name}"></form>
        """,
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


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://id.vut.cz/authenticated", "Studis"),
        ("https://www.vut.cz/landing", "Elektronický index"),
    ],
)
def test_studis_title_on_unrelated_url_is_not_authenticated(url: str, title: str) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        html=f"<title>{title}</title>",
    )

    assert _looks_authenticated(response) is False


@pytest.mark.parametrize(
    ("status_code", "title"),
    [
        (200, "Studis - Maintenance"),
        (200, "Studis - Access denied"),
        (403, "Studis"),
        (503, "Elektronický index"),
    ],
)
def test_studis_error_or_non_studis_page_is_not_authenticated(
    status_code: int,
    title: str,
) -> None:
    response = httpx.Response(
        status_code,
        request=httpx.Request(
            "GET",
            "https://www.vut.cz/studis/student.phtml?sn=el_index",
        ),
        html=f"<title>{title}</title>",
    )

    assert _looks_authenticated(response) is False


@pytest.mark.asyncio
@respx.mock
async def test_refresh_session_cookie_requires_authenticated_result() -> None:
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            html=META_HOME_REFRESH,
        )
    )
    respx.get("https://id.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <form method="post" action="/auth/common/home/default?authSectionId=abc">
              <input type="text" name="login">
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
            </form>
            """,
        )
    )
    respx.post("https://id.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        return_value=httpx.Response(200, html="<title>Jednotné přihlášení VUT</title>")
    )

    with pytest.raises(StudisAuthError, match="authenticated Studis session"):
        await refresh_session_cookie(_settings())


@pytest.mark.asyncio
async def test_refresh_session_cookie_rejects_authenticated_empty_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authenticated_without_cookie(
        settings: Settings | None = None,
    ) -> LoginAttemptResult:
        del settings
        return LoginAttemptResult(
            final_url="https://www.vut.cz/studis/student.phtml?sn=el_index",
            status_code=200,
            authenticated=True,
            cookie_names=[],
            session_cookie="",
            title="Elektronický index",
        )

    monkeypatch.setattr(
        "vut_studis.auth.login_with_password",
        authenticated_without_cookie,
    )

    with pytest.raises(StudisAuthError, match="authenticated Studis session"):
        await refresh_session_cookie(_settings())
