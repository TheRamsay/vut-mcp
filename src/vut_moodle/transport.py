"""Origin-scoped, separately persisted Moodle session transport."""

from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from vut_moodle.auth import refresh_moodle_session_cookie
from vut_moodle.errors import MoodleAuthError
from vut_studis.auth import _cookie_header_for_url
from vut_studis.config import ENV_PATH, Settings, set_env_value


class MoodleTransport:
    def __init__(self, settings: Settings, *, env_path: Path | None = None) -> None:
        self.settings = settings
        self.env_path = env_path or ENV_PATH

    async def get_html(self, path: str) -> str:
        return (await self.get_response(path)).text

    async def get_response(self, path: str) -> httpx.Response:
        requested_url = self._resolve_request_url(path)
        await self._ensure_session_cookie()
        response = await self._request_authenticated(path, requested_url)
        if response is not None:
            return response

        await self._refresh_session_cookie()
        response = await self._request_authenticated(path, requested_url)
        if response is None:
            raise MoodleAuthError(
                "Moodle session refresh succeeded, but the retry was not authenticated."
            )
        return response

    async def _request_authenticated(
        self,
        path: str,
        requested_url: str,
    ) -> httpx.Response | None:
        cookie_jar = self._session_cookie_jar(requested_url)
        async with self._http_client(cookie_jar) as client:
            response = await client.get(path)
            response.raise_for_status()
            if _is_moodle_login_response(response, base_url=str(self.settings.moodle_base_url)):
                return None

            requested_origin = _origin(requested_url)
            persisted_cookies = self._session_cookie_jar(requested_url)
            persisted = httpx.Cookies(persisted_cookies)
            for received_response in [*response.history, response]:
                if _origin(str(received_response.request.url)) == requested_origin:
                    persisted.extract_cookies(received_response)
            self._persist_cookie_jar(persisted_cookies, requested_url)
            return response

    def _resolve_request_url(self, path: str) -> str:
        base_url = str(self.settings.moodle_base_url)
        requested_url = urljoin(base_url, path)
        if _origin(requested_url) != _origin(base_url):
            raise MoodleAuthError(
                "Authenticated Moodle requests must remain on the configured Moodle origin."
            )
        return requested_url

    def _http_client(self, cookie_jar: CookieJar) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=str(self.settings.moodle_base_url),
            follow_redirects=True,
            timeout=self.settings.http_timeout_seconds,
            cookies=cookie_jar,
            event_hooks={"request": [self._strip_off_origin_cookies]},
        )

    async def _strip_off_origin_cookies(self, request: httpx.Request) -> None:
        if _origin(str(request.url)) != _origin(str(self.settings.moodle_base_url)):
            request.headers.pop("cookie", None)

    def _session_cookie_jar(self, requested_url: str) -> CookieJar:
        if not self.settings.moodle_session_cookie:
            raise MoodleAuthError("VUT_MOODLE_SESSION_COOKIE is not configured.")

        parsed = urlparse(requested_url)
        if parsed.hostname is None:
            raise MoodleAuthError("The Moodle request URL does not contain a hostname.")
        cookie_jar = CookieJar(
            policy=DefaultCookiePolicy(
                strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain,
            )
        )
        for name, value in _cookie_values(self.settings.moodle_session_cookie):
            cookie_jar.set_cookie(
                Cookie(
                    version=0,
                    name=name,
                    value=value,
                    port=None,
                    port_specified=False,
                    domain=parsed.hostname,
                    domain_specified=False,
                    domain_initial_dot=False,
                    path="/",
                    path_specified=True,
                    secure=parsed.scheme.casefold() == "https",
                    expires=None,
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={},
                    rfc2109=False,
                )
            )
        return cookie_jar

    def _persist_cookie_jar(self, cookie_jar: CookieJar, requested_url: str) -> None:
        session_cookie = _cookie_header_for_url(cookie_jar, requested_url)
        if session_cookie == self.settings.moodle_session_cookie:
            return
        set_env_value(self.env_path, "VUT_MOODLE_SESSION_COOKIE", session_cookie)
        self.settings.moodle_session_cookie = session_cookie or None

    async def _ensure_session_cookie(self) -> None:
        if self.settings.moodle_session_cookie:
            return
        if not self.settings.username or not self.settings.password:
            raise MoodleAuthError(
                "VUT_MOODLE_SESSION_COOKIE is not configured and VUT_USERNAME/VUT_PASSWORD "
                "are not available for automatic login."
            )
        await self._refresh_session_cookie()

    async def _refresh_session_cookie(self) -> None:
        session_cookie = await refresh_moodle_session_cookie(self.settings)
        set_env_value(self.env_path, "VUT_MOODLE_SESSION_COOKIE", session_cookie)
        self.settings.moodle_session_cookie = session_cookie


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = parsed.scheme.casefold()
    if not scheme or parsed.hostname is None:
        raise MoodleAuthError("Authenticated Moodle requests require an absolute HTTP URL.")
    try:
        port = parsed.port
    except ValueError as error:
        raise MoodleAuthError("Moodle request URL has an invalid port.") from error
    return scheme, parsed.hostname.casefold(), port or {"http": 80, "https": 443}.get(scheme)


def _cookie_values(header: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for segment in header.split(";"):
        cookie = SimpleCookie()
        cookie.load(segment.strip())
        values.extend((morsel.key, morsel.value) for morsel in cookie.values())
    return values


def _is_moodle_login_response(response: httpx.Response, *, base_url: str) -> bool:
    parsed = urlparse(str(response.url))
    base = urlparse(base_url)
    return (
        parsed.hostname is None
        or parsed.hostname.casefold() != (base.hostname or "").casefold()
        or parsed.path == "/login/index.php"
    )
