import time
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy, http2time
from http.cookies import Morsel, SimpleCookie
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from vut_studis.auth import (
    _cookie_header_for_url,
    is_login_response,
    refresh_session_cookie,
)
from vut_studis.config import ENV_PATH, Settings, set_env_value
from vut_studis.errors import StudisAuthError


class StudisTransport:
    def __init__(self, settings: Settings, *, env_path: Path | None = None) -> None:
        self.settings = settings
        self.env_path = env_path or ENV_PATH

    async def get_html(self, path: str) -> str:
        response = await self.get_response(path)
        return response.text

    async def get_response(self, path: str) -> httpx.Response:
        requested_url = self._resolve_request_url(path)
        await self._ensure_session_cookie()
        response = await self._request_authenticated(path, requested_url)
        if response is not None:
            return response

        if not self._can_refresh_session():
            raise StudisAuthError(
                "Studis session expired. Run `uv run vut-studis-debug login-refresh-session`."
            )

        await self._refresh_session_cookie()
        response = await self._request_authenticated(path, requested_url)
        if response is None:
            raise StudisAuthError(
                "Studis session refresh succeeded, but the retry was not authenticated."
            )

        return response

    async def _request_authenticated(
        self,
        path: str,
        requested_url: str,
    ) -> httpx.Response | None:
        client_cookie_jar = self._session_cookie_jar(requested_url)
        persistence_cookie_jar = self._session_cookie_jar(requested_url)
        async with self._http_client(client_cookie_jar) as client:
            response = await client.get(path)
            response.raise_for_status()
            if is_login_response(response):
                return None

            requested_origin = _origin(requested_url)
            same_origin_responses = [
                received_response
                for received_response in [*response.history, response]
                if _origin(str(received_response.request.url)) == requested_origin
            ]
            persistence_cookies = httpx.Cookies(persistence_cookie_jar)
            for received_response in same_origin_responses:
                persistence_cookies.extract_cookies(received_response)

            final_operations = _final_cookie_operations(same_origin_responses)
            _remove_cookies_by_name(
                persistence_cookie_jar,
                _synthetic_cookie_deletion_names(final_operations, requested_url),
                urlparse(requested_url).hostname,
            )
            self._persist_cookie_jar(persistence_cookie_jar, requested_url)
            return response

    def _resolve_request_url(self, path: str) -> str:
        base_url = str(self.settings.base_url)
        requested_url = urljoin(base_url, path)
        if _origin(requested_url) != _origin(base_url):
            raise StudisAuthError(
                "Authenticated Studis requests must remain on the configured base origin."
            )
        return requested_url

    def _http_client(self, cookie_jar: CookieJar) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=str(self.settings.base_url),
            follow_redirects=True,
            timeout=self.settings.http_timeout_seconds,
            cookies=cookie_jar,
            event_hooks={"request": [self._strip_off_origin_cookies]},
        )

    async def _strip_off_origin_cookies(self, request: httpx.Request) -> None:
        # HTTPX copies its cookie jar with a default policy while building redirects.
        if _origin(str(request.url)) != _origin(str(self.settings.base_url)):
            request.headers.pop("cookie", None)

    def _session_cookie_jar(self, requested_url: str) -> CookieJar:
        if not self.settings.session_cookie:
            raise StudisAuthError("VUT_SESSION_COOKIE is not configured.")

        parsed_url = urlparse(requested_url)
        host = parsed_url.hostname
        if host is None:
            raise StudisAuthError("The requested URL does not contain a hostname.")

        policy = DefaultCookiePolicy(
            strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain,
        )
        cookie_jar = CookieJar(policy=policy)
        for name, value in _cookie_values(self.settings.session_cookie):
            cookie_jar.set_cookie(
                Cookie(
                    version=0,
                    name=name,
                    value=value,
                    port=None,
                    port_specified=False,
                    domain=host,
                    domain_specified=False,
                    domain_initial_dot=False,
                    path="/",
                    path_specified=True,
                    secure=parsed_url.scheme.casefold() == "https",
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
        session_cookie = _canonical_cookie_header(
            _cookie_header_for_url(cookie_jar, requested_url)
        )
        if session_cookie == self.settings.session_cookie:
            return

        set_env_value(self.env_path, "VUT_SESSION_COOKIE", session_cookie)
        self.settings.session_cookie = session_cookie or None

    async def _ensure_session_cookie(self) -> None:
        if self.settings.session_cookie:
            return

        if not self._can_refresh_session():
            raise StudisAuthError(
                "VUT_SESSION_COOKIE is not configured and VUT_USERNAME/VUT_PASSWORD "
                "are not available for automatic login."
            )

        await self._refresh_session_cookie()

    def _can_refresh_session(self) -> bool:
        return bool(self.settings.username and self.settings.password)

    async def _refresh_session_cookie(self) -> None:
        session_cookie = await refresh_session_cookie(self.settings)
        set_env_value(self.env_path, "VUT_SESSION_COOKIE", session_cookie)
        self.settings.session_cookie = session_cookie


def _cookie_segments(header: str) -> list[str]:
    segments: list[str] = []
    segment_start = 0
    quoted = False
    escaped = False

    for index, character in enumerate(header):
        if escaped:
            escaped = False
        elif quoted and character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif character == ";" and not quoted:
            segments.append(header[segment_start:index].strip())
            segment_start = index + 1

    segments.append(header[segment_start:].strip())
    return [segment for segment in segments if segment]


def _cookie_values(header: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for segment in _cookie_segments(header):
        parsed = SimpleCookie()
        parsed.load(segment)
        for morsel in parsed.values():
            if morsel.key in seen_names:
                continue
            seen_names.add(morsel.key)
            values.append((morsel.key, morsel.value))
    return values


def _canonical_cookie_header(header: str) -> str:
    segments: list[str] = []
    seen_names: set[str] = set()
    for segment in _cookie_segments(header):
        parsed = SimpleCookie()
        parsed.load(segment)
        names = [morsel.key for morsel in parsed.values()]
        if not names or all(name in seen_names for name in names):
            continue
        segments.append(segment)
        seen_names.update(names)
    return "; ".join(segments)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = parsed.scheme.casefold()
    host = parsed.hostname
    if not scheme or host is None:
        raise StudisAuthError("Authenticated Studis requests require an absolute HTTP URL.")

    try:
        port = parsed.port
    except ValueError as error:
        raise StudisAuthError("Authenticated Studis request URL has an invalid port.") from error

    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    return scheme, host.casefold(), port


def _final_cookie_operations(
    responses: list[httpx.Response],
) -> dict[tuple[str, str, str], bool]:
    final_operations: dict[tuple[str, str, str], bool] = {}
    for response in responses:
        response_url = urlparse(str(response.request.url))
        response_host = response_url.hostname
        if response_host is None:
            continue

        for header in response.headers.get_list("set-cookie"):
            parsed = SimpleCookie()
            parsed.load(header)
            for morsel in parsed.values():
                domain = (morsel["domain"] or response_host).lstrip(".").casefold()
                normalized_response_host = response_host.casefold()
                if not (
                    normalized_response_host == domain
                    or normalized_response_host.endswith(f".{domain}")
                ):
                    continue

                path = morsel["path"]
                if not path.startswith("/"):
                    path = _default_cookie_path(response_url.path)
                final_operations[(morsel.key, domain, path)] = _is_cookie_deletion(morsel)

    return final_operations


def _default_cookie_path(request_path: str) -> str:
    if not request_path.startswith("/") or request_path.count("/") <= 1:
        return "/"
    return request_path.rsplit("/", 1)[0] or "/"


def _synthetic_cookie_deletion_names(
    final_operations: dict[tuple[str, str, str], bool],
    requested_url: str,
) -> set[str]:
    requested = urlparse(requested_url)
    requested_host = requested.hostname
    if requested_host is None:
        return set()

    requested_path = requested.path or "/"
    operations_by_name: dict[str, set[bool]] = {}
    for (name, domain, path), is_deletion in final_operations.items():
        if not _cookie_scope_applies(
            domain,
            path,
            requested_host,
            requested_path,
        ):
            continue
        operations_by_name.setdefault(name, set()).add(is_deletion)
    return {
        name
        for name, operations in operations_by_name.items()
        if operations == {True}
    }


def _cookie_scope_applies(
    domain: str,
    path: str,
    request_host: str,
    request_path: str,
) -> bool:
    normalized_domain = domain.lstrip(".").casefold()
    normalized_host = request_host.casefold()
    if normalized_host != normalized_domain and not normalized_host.endswith(
        f".{normalized_domain}"
    ):
        return False

    if not request_path.startswith(path):
        return False
    return path.endswith("/") or len(request_path) == len(path) or request_path[len(path)] == "/"


def _is_cookie_deletion(morsel: Morsel[str]) -> bool:
    max_age = morsel["max-age"]
    if max_age:
        try:
            if int(max_age) <= 0:
                return True
        except ValueError:
            pass

    expires = morsel["expires"]
    expires_at = http2time(expires) if expires else None
    return expires_at is not None and expires_at <= time.time()


def _remove_cookies_by_name(
    cookie_jar: CookieJar,
    names: set[str],
    host: str | None,
) -> None:
    if not names or host is None:
        return

    normalized_host = host.casefold()
    for cookie in list(cookie_jar):
        if cookie.name not in names or cookie.domain.lstrip(".").casefold() != normalized_host:
            continue
        cookie_jar.clear(cookie.domain, cookie.path, cookie.name)
