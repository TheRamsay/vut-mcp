from pathlib import Path

import httpx
import pytest
import respx

from vut_moodle.errors import MoodleAuthError
from vut_moodle.transport import MoodleTransport
from vut_studis.config import Settings


def _settings(
    *,
    moodle_session_cookie: str | None = "MoodleSession=expired",
) -> Settings:
    return Settings(
        VUT_BASE_URL="https://www.vut.cz",
        VUT_USERNAME="",
        VUT_PASSWORD="",
        VUT_SESSION_COOKIE="",
        VUT_MOODLE_BASE_URL="https://moodle.vut.cz",
        VUT_MOODLE_ACCESS_MODE="auto",
        VUT_MOODLE_SESSION_COOKIE=moodle_session_cookie,
    )


@pytest.mark.asyncio
@respx.mock
async def test_moodle_transport_refreshes_once_and_persists_only_moodle_cookie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refresh(settings: Settings) -> str:
        assert settings.moodle_session_cookie == "MoodleSession=expired"
        return "MoodleSession=fresh"

    monkeypatch.setattr("vut_moodle.transport.refresh_moodle_session_cookie", refresh)
    respx.get("https://moodle.vut.cz/my/").mock(
        side_effect=[
            httpx.Response(302, headers={"location": "/login/index.php"}),
            httpx.Response(200, html="<title>Dashboard</title>"),
        ]
    )
    respx.get("https://moodle.vut.cz/login/index.php").mock(
        return_value=httpx.Response(200, html="<title>Login</title>")
    )
    env_path = tmp_path / ".env"
    settings = _settings()
    original_studis_cookie = settings.session_cookie
    transport = MoodleTransport(settings, env_path=env_path)

    response = await transport.get_response("/my/")

    assert response.status_code == 200
    assert settings.moodle_session_cookie == "MoodleSession=fresh"
    assert settings.session_cookie == original_studis_cookie
    assert 'VUT_MOODLE_SESSION_COOKIE="MoodleSession=fresh"' in env_path.read_text()
    assert "VUT_SESSION_COOKIE" not in env_path.read_text()


@pytest.mark.asyncio
@respx.mock
async def test_moodle_transport_never_sends_moodle_cookie_to_id_vut_cz() -> None:
    seen_headers: list[str | None] = []
    respx.get("https://moodle.vut.cz/my/").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://id.vut.cz/auth/common/"},
        )
    )
    respx.get("https://id.vut.cz/auth/common/").mock(
        side_effect=lambda request: seen_headers.append(request.headers.get("cookie"))
        or httpx.Response(200, html="<input name=login>")
    )

    async def no_refresh(settings: Settings) -> str:
        del settings
        raise MoodleAuthError("refresh unavailable")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("vut_moodle.transport.refresh_moodle_session_cookie", no_refresh)
    try:
        with pytest.raises(MoodleAuthError):
            transport = MoodleTransport(_settings(moodle_session_cookie="MoodleSession=keep"))
            await transport.get_response("/my/")
    finally:
        monkeypatch.undo()

    assert seen_headers == [None]


@pytest.mark.asyncio
@respx.mock
async def test_moodle_transport_persists_rotating_moodle_cookie(tmp_path: Path) -> None:
    settings = _settings(moodle_session_cookie="MoodleSession=old")
    respx.get("https://moodle.vut.cz/my/").mock(
        return_value=httpx.Response(
            200,
            headers={"set-cookie": "MoodleSession=rotated; Path=/"},
            html="<title>Dashboard</title>",
        )
    )

    await MoodleTransport(settings, env_path=tmp_path / ".env").get_response("/my/")

    assert settings.moodle_session_cookie == "MoodleSession=rotated"


@pytest.mark.asyncio
@respx.mock
async def test_moodle_transport_rejects_off_origin_url_without_a_request(tmp_path: Path) -> None:
    target_url = "https://evil.example/my/"
    route = respx.get(target_url).mock(
        return_value=httpx.Response(200, html="<title>Unexpected</title>")
    )
    transport = MoodleTransport(
        _settings(moodle_session_cookie="MoodleSession=keep"),
        env_path=tmp_path / ".env",
    )

    with pytest.raises(MoodleAuthError, match="configured Moodle origin"):
        await transport.get_response(target_url)

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_off_origin_redirect_cookie_cannot_replace_moodle_session(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('VUT_MOODLE_SESSION_COOKIE="MoodleSession=old"\n')
    redirected_cookie_headers: list[str | None] = []

    respx.get("https://moodle.vut.cz/my/").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://evil.example/landing"},
        )
    )
    respx.get("https://evil.example/landing").mock(
        return_value=httpx.Response(
            302,
            headers={
                "location": "https://moodle.vut.cz/landing",
                "set-cookie": "MoodleSession=attacker; Domain=moodle.vut.cz; Path=/",
            },
        )
    )

    def final_response(request: httpx.Request) -> httpx.Response:
        redirected_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(200, html="<title>Dashboard</title>")

    respx.get("https://moodle.vut.cz/landing").mock(side_effect=final_response)
    settings = _settings(moodle_session_cookie="MoodleSession=old")

    await MoodleTransport(settings, env_path=env_path).get_response("/my/")

    assert redirected_cookie_headers == ["MoodleSession=old"]
    assert settings.moodle_session_cookie == "MoodleSession=old"
    assert env_path.read_text() == 'VUT_MOODLE_SESSION_COOKIE="MoodleSession=old"\n'
