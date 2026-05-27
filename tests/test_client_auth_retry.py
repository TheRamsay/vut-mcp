from urllib.parse import parse_qs

import httpx
import pytest
import respx

from vut_studis.client import StudisClient
from vut_studis.config import Settings
from vut_studis.errors import StudisAuthError

META_HOME_REFRESH = (
    '<meta http-equiv="refresh" content="0; url=/auth/common/home/default?authSectionId=abc">'
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
    monkeypatch.setattr("vut_studis.client.ENV_PATH", tmp_path / ".env")
    captured_password_payload: dict[str, list[str]] = {}

    respx.get("https://www.vut.cz/studis/student.phtml?sn=el_index").mock(
        side_effect=[
            httpx.Response(200, html="<title>Jednotné přihlášení VUT</title>"),
            httpx.Response(200, html=META_HOME_REFRESH),
            httpx.Response(200, html="<title>Elektronický index</title>"),
            httpx.Response(200, html="<title>Retried Studis page</title>"),
        ]
    )
    respx.get("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
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
    respx.post("https://www.vut.cz/auth/common/home/default?authSectionId=abc").mock(
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
            headers={"set-cookie": "VUTSESSIONID=fresh-session; Path=/"},
            html='<meta http-equiv="refresh" content="0; url=/studis/student.phtml?sn=el_index">',
        )

    respx.post("https://www.vut.cz/auth/common/password/default?authSectionId=abc").mock(
        side_effect=password_submit
    )

    client = StudisClient(_settings())
    html = await client._get_html("/studis/student.phtml?sn=el_index")

    assert "Retried Studis page" in html
    assert client.settings.session_cookie == "VUTSESSIONID=fresh-session"
    assert 'VUT_SESSION_COOKIE="VUTSESSIONID=fresh-session"' in (tmp_path / ".env").read_text()
    assert captured_password_payload["passwd"] == ["secret"]


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
