"""Origin-scoped, separately persisted Moodle session transport."""

from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from vut_moodle.auth import refresh_moodle_session_cookie
from vut_moodle.errors import MoodleAuthError, MoodleContentError
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

    async def get_same_origin_response(self, path: str) -> httpx.Response:
        """Fetch HTML while refusing redirects before any off-origin request is made."""
        requested_url = self._resolve_request_url(path)
        await self._ensure_session_cookie()
        response = await self._request_same_origin_authenticated(path, requested_url)
        if response is not None:
            return response

        await self._refresh_session_cookie()
        response = await self._request_same_origin_authenticated(path, requested_url)
        if response is None:
            raise MoodleAuthError(
                "Moodle session refresh succeeded, but the retry was not authenticated."
            )
        return response

    async def download_file(self, path: str, *, max_bytes: int) -> tuple[bytes, str | None]:
        """Stream one same-origin Moodle plugin file into a bounded in-memory buffer."""
        if max_bytes < 1:
            raise MoodleContentError("Moodle attachment byte limit must be positive.")
        requested_url = self._resolve_request_url(path)
        if not urlparse(requested_url).path.startswith("/pluginfile.php/"):
            raise MoodleContentError("Moodle attachment URL must use the pluginfile.php path.")

        await self._ensure_session_cookie()
        response = await self._download_authenticated(path, requested_url, max_bytes=max_bytes)
        if response is not None:
            return response

        await self._refresh_session_cookie()
        response = await self._download_authenticated(path, requested_url, max_bytes=max_bytes)
        if response is None:
            raise MoodleAuthError(
                "Moodle session refresh succeeded, but the attachment retry was not authenticated."
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

    async def _request_same_origin_authenticated(
        self,
        path: str,
        requested_url: str,
    ) -> httpx.Response | None:
        cookie_jar = self._session_cookie_jar(requested_url)
        responses: list[httpx.Response] = []
        current_url = path
        async with self._http_client(cookie_jar, follow_redirects=False) as client:
            for _ in range(10):
                response = await client.get(current_url)
                if response.is_redirect:
                    location = response.headers.get("location")
                    target_url = urljoin(str(response.url), location or "")
                    if not location or _origin(target_url) != _origin(requested_url):
                        raise MoodleAuthError(
                            "Moodle resource redirects must remain on the configured Moodle origin."
                        )
                    responses.append(response)
                    current_url = target_url
                    continue
                response.raise_for_status()
                if _is_moodle_login_response(response, base_url=str(self.settings.moodle_base_url)):
                    return None
                responses.append(response)
                persisted = httpx.Cookies(cookie_jar)
                for received_response in responses:
                    persisted.extract_cookies(received_response)
                self._persist_cookie_jar(cookie_jar, requested_url)
                return response
        raise MoodleAuthError("Moodle resource redirect limit of 10 exceeded.")

    async def _download_authenticated(
        self,
        path: str,
        requested_url: str,
        *,
        max_bytes: int,
    ) -> tuple[bytes, str | None] | None:
        cookie_jar = self._session_cookie_jar(requested_url)
        async with self._http_client(cookie_jar) as client:
            async with client.stream("GET", path) as response:
                response.raise_for_status()
                if any(
                    _origin(str(received_response.request.url)) != _origin(requested_url)
                    for received_response in [*response.history, response]
                ):
                    raise MoodleAuthError(
                        "Moodle attachment redirects must remain on the configured Moodle origin."
                    )
                if _is_moodle_login_response(response, base_url=str(self.settings.moodle_base_url)):
                    return None
                _check_content_length(response, max_bytes=max_bytes)

                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise MoodleContentError(
                            f"Moodle attachment byte limit of {max_bytes} exceeded."
                        )
                    content.extend(chunk)

                self._persist_received_moodle_cookies(cookie_jar, response, requested_url)
                return bytes(content), response.headers.get("content-type")

    def _resolve_request_url(self, path: str) -> str:
        base_url = str(self.settings.moodle_base_url)
        requested_url = urljoin(base_url, path)
        if _origin(requested_url) != _origin(base_url):
            raise MoodleAuthError(
                "Authenticated Moodle requests must remain on the configured Moodle origin."
            )
        return requested_url

    def _http_client(
        self,
        cookie_jar: CookieJar,
        *,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=str(self.settings.moodle_base_url),
            follow_redirects=follow_redirects,
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

    def _persist_received_moodle_cookies(
        self,
        cookie_jar: CookieJar,
        response: httpx.Response,
        requested_url: str,
    ) -> None:
        requested_origin = _origin(requested_url)
        persisted = httpx.Cookies(cookie_jar)
        for received_response in [*response.history, response]:
            if _origin(str(received_response.request.url)) == requested_origin:
                persisted.extract_cookies(received_response)
        self._persist_cookie_jar(cookie_jar, requested_url)

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


def _check_content_length(response: httpx.Response, *, max_bytes: int) -> None:
    content_length = response.headers.get("content-length")
    if content_length is None:
        return
    try:
        declared_bytes = int(content_length)
    except ValueError as error:
        raise MoodleContentError(
            "Moodle attachment has an invalid Content-Length header."
        ) from error
    if declared_bytes < 0:
        raise MoodleContentError("Moodle attachment has an invalid Content-Length header.")
    if declared_bytes > max_bytes:
        raise MoodleContentError(f"Moodle attachment byte limit of {max_bytes} exceeded.")
