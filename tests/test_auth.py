from urllib.parse import parse_qs

import httpx
import pytest
import respx

from vut_studis.auth import inspect_login_flow, login_with_password, refresh_session_cookie
from vut_studis.config import Settings
from vut_studis.errors import StudisAuthError

META_HOME_REFRESH = (
    '<meta http-equiv="refresh" content="0; url=/auth/common/home/default?authSectionId=abc">'
)


def _settings() -> Settings:
    return Settings(
        VUT_BASE_URL="https://www.vut.cz",
        VUT_USERNAME="test-user",
        VUT_PASSWORD="secret",
    )


@pytest.mark.asyncio
@respx.mock
async def test_inspect_login_flow_follows_meta_refresh() -> None:
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            html="""
            <title>Jednotné přihlášení VUT</title>
            <meta http-equiv="refresh" content="0; url=/auth/common/home/default?authSectionId=abc">
            """,
        )
    )
    respx.get("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
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
async def test_login_with_password_returns_session_cookie() -> None:
    captured_password_payload: dict[str, list[str]] = {}

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=[
            httpx.Response(
                200,
                html=META_HOME_REFRESH,
            ),
            httpx.Response(200, html="<title>Elektronický index</title>"),
        ]
    )
    respx.get("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
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
    respx.post("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
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
            headers={"set-cookie": "VUTSESSIONID=session-value; Path=/"},
            html='<meta http-equiv="refresh" content="0; url=/studis/student.phtml?sn=el_index">',
        )

    respx.post("https://www.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        side_effect=password_submit
    )
    result = await login_with_password(_settings())

    assert result.authenticated is True
    assert result.final_url == "https://www.vut.cz/studis/student.phtml?sn=el_index"
    assert result.session_cookie == "VUTSESSIONID=session-value"
    assert captured_password_payload["passwd"] == ["secret"]
    assert "fingerprintData" in captured_password_payload


@pytest.mark.asyncio
@respx.mock
async def test_refresh_session_cookie_requires_authenticated_result() -> None:
    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        return_value=httpx.Response(
            200,
            html=META_HOME_REFRESH,
        )
    )
    respx.get("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <form method="post" action="/auth/common/home/default?authSectionId=abc">
              <input type="text" name="login">
            </form>
            """,
        )
    )
    respx.post("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
        return_value=httpx.Response(
            200,
            html="""
            <form method="post" action="/auth/common/password/default?authSectionId=abc">
              <input type="password" name="passwd">
            </form>
            """,
        )
    )
    respx.post("https://www.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        return_value=httpx.Response(200, html="<title>Jednotné přihlášení VUT</title>")
    )

    with pytest.raises(StudisAuthError, match="authenticated Studis page"):
        await refresh_session_cookie(_settings())
