"""Moodle-specific authentication built on the shared VUT SSO flow."""

from urllib.parse import urljoin, urlparse

import httpx

from vut_moodle.errors import MoodleAuthError
from vut_studis.auth import login_via_vut_sso
from vut_studis.config import Settings
from vut_studis.errors import StudisAuthError

MOODLE_LOGIN_PATH = "/auth/oidc/?source=loginpage"


async def refresh_moodle_session_cookie(settings: Settings) -> str:
    entry_url = urljoin(str(settings.moodle_base_url), MOODLE_LOGIN_PATH)
    try:
        result = await login_via_vut_sso(
            settings,
            entry_url=entry_url,
            target_origin=str(settings.moodle_base_url),
            authenticated=lambda response: _looks_like_moodle_home(
                response,
                base_url=str(settings.moodle_base_url),
            ),
        )
    except StudisAuthError as error:
        raise MoodleAuthError(str(error)) from error
    if not result.authenticated or not result.session_cookie:
        raise MoodleAuthError("Login did not produce an authenticated Moodle session.")
    return result.session_cookie


def _looks_like_moodle_home(response: httpx.Response, *, base_url: str) -> bool:
    parsed = urlparse(str(response.url))
    expected = urlparse(base_url)
    return (
        200 <= response.status_code < 300
        and parsed.hostname is not None
        and parsed.hostname.casefold() == (expected.hostname or "").casefold()
        and parsed.path != "/login/index.php"
    )
