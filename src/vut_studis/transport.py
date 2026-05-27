from pathlib import Path

import httpx

from vut_studis.auth import refresh_session_cookie
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
        await self._ensure_session_cookie()
        response = await self._request_authenticated(path)
        if response is not None:
            return response

        if not self._can_refresh_session():
            raise StudisAuthError(
                "Studis session expired. Run `uv run vut-studis-debug login-refresh-session`."
            )

        await self._refresh_session_cookie()
        response = await self._request_authenticated(path)
        if response is None:
            raise StudisAuthError(
                "Studis session refresh succeeded, but the retry was not authenticated."
            )

        return response

    async def _request_authenticated(self, path: str) -> httpx.Response | None:
        async with self._http_client() as client:
            response = await client.get(path)
            response.raise_for_status()
            if self._is_login_response(response):
                return None
            return response

    def _headers(self) -> dict[str, str]:
        if not self.settings.session_cookie:
            raise StudisAuthError("VUT_SESSION_COOKIE is not configured.")

        return {"Cookie": self.settings.session_cookie}

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=str(self.settings.base_url),
            follow_redirects=True,
            timeout=self.settings.http_timeout_seconds,
            headers=self._headers(),
        )

    def _is_login_response(self, response: httpx.Response) -> bool:
        title_start = response.text[:2000].lower()
        return "jednotné přihlášení vut" in title_start or "auth/common" in str(response.url)

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

