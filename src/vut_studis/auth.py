import json
import re
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from vut_studis.config import Settings, load_settings
from vut_studis.errors import StudisAuthError

STUDIS_ENTRY_PATH = "/studis/student.phtml?sn=el_index"


@dataclass(frozen=True)
class FormField:
    name: str
    field_type: str | None
    value_present: bool


@dataclass(frozen=True)
class LoginForm:
    method: str
    action: str
    fields: list[FormField]


@dataclass(frozen=True)
class LoginPageSnapshot:
    requested_url: str
    final_url: str
    status_code: int
    redirect_chain: list[str]
    title: str | None
    forms: list[LoginForm]


@dataclass(frozen=True)
class LoginAttemptResult:
    final_url: str
    status_code: int
    authenticated: bool
    cookie_names: list[str]
    session_cookie: str
    title: str | None


async def refresh_session_cookie(settings: Settings | None = None) -> str:
    result = await login_with_password(settings)
    if not result.authenticated:
        raise StudisAuthError("Login did not reach an authenticated Studis page.")

    return result.session_cookie


def _input_value_present(value: str | None) -> bool:
    return value is not None and value != ""


def _parse_forms(html: str, base_url: str) -> list[LoginForm]:
    tree = HTMLParser(html)
    forms: list[LoginForm] = []

    for form in tree.css("form"):
        method = (form.attributes.get("method") or "get").lower()
        action = urljoin(base_url, form.attributes.get("action") or base_url)
        fields: list[FormField] = []

        for input_node in form.css("input"):
            name = input_node.attributes.get("name")
            if not name:
                continue

            fields.append(
                FormField(
                    name=name,
                    field_type=input_node.attributes.get("type"),
                    value_present=_input_value_present(input_node.attributes.get("value")),
                )
            )

        forms.append(LoginForm(method=method, action=action, fields=fields))

    return forms


def _form_values(html: str, base_url: str, required_field: str) -> tuple[str, dict[str, str]]:
    tree = HTMLParser(html)
    for form in tree.css("form"):
        values: dict[str, str] = {}
        has_required_field = False

        for input_node in form.css("input"):
            name = input_node.attributes.get("name")
            if not name:
                continue

            if name == required_field:
                has_required_field = True
            values[name] = input_node.attributes.get("value") or ""

        if has_required_field:
            action = urljoin(base_url, form.attributes.get("action") or base_url)
            return action, values

    raise StudisAuthError(f"Login form with field {required_field!r} was not found.")


def _parse_title(html: str) -> str | None:
    tree = HTMLParser(html)
    title = tree.css_first("title")
    if title is None:
        return None

    text = title.text(strip=True)
    return text or None


async def inspect_login_flow(settings: Settings | None = None) -> list[LoginPageSnapshot]:
    settings = settings or load_settings()
    entry_url = urljoin(str(settings.base_url), STUDIS_ENTRY_PATH)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.http_timeout_seconds,
    ) as client:
        entry_response = await client.get(entry_url)
        snapshots = [_snapshot_response(entry_url, entry_response)]

        next_url = _next_login_url(entry_response)
        seen_urls = {str(entry_response.url)}
        while next_url is not None and next_url not in seen_urls and len(snapshots) < 5:
            seen_urls.add(next_url)
            next_response = await client.get(next_url)
            snapshots.append(_snapshot_response(next_url, next_response))
            next_url = _next_login_url(next_response)

    return snapshots


async def login_with_password(settings: Settings | None = None) -> LoginAttemptResult:
    settings = settings or load_settings()
    if not settings.username or not settings.password:
        raise StudisAuthError("VUT_USERNAME and VUT_PASSWORD must be configured in .env.")

    entry_url = urljoin(str(settings.base_url), STUDIS_ENTRY_PATH)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=settings.http_timeout_seconds,
    ) as client:
        entry_response = await client.get(entry_url)
        home_response = await _follow_login_meta_refresh(client, entry_response)

        username_action, username_payload = _form_values(
            home_response.text,
            str(home_response.url),
            required_field="login",
        )
        username_payload["login"] = settings.username
        username_response = await client.post(username_action, data=username_payload)
        password_response = await _follow_login_meta_refresh(client, username_response)

        password_action, password_payload = _form_values(
            password_response.text,
            str(password_response.url),
            required_field="passwd",
        )
        password_payload["passwd"] = settings.password
        if "fingerprintData" in password_payload and not password_payload["fingerprintData"]:
            password_payload["fingerprintData"] = json.dumps(
                {
                    "language": [["en-US"], ["en-US", "en"]],
                    "javascriptEnable": True,
                    "timezone": "Europe/Prague",
                },
                separators=(",", ":"),
            )

        final_response = await client.post(password_action, data=password_payload)
        final_response = await _follow_login_meta_refresh(client, final_response)

    return LoginAttemptResult(
        final_url=str(final_response.url),
        status_code=final_response.status_code,
        authenticated=_looks_authenticated(final_response),
        cookie_names=sorted(cookie.name for cookie in client.cookies.jar),
        session_cookie=_cookie_header(client.cookies.jar),
        title=_parse_title(final_response.text),
    )


def _snapshot_response(requested_url: str, response: httpx.Response) -> LoginPageSnapshot:
    final_url = str(response.url)
    return LoginPageSnapshot(
        requested_url=requested_url,
        final_url=final_url,
        status_code=response.status_code,
        redirect_chain=[str(item.url) for item in response.history],
        title=_parse_title(response.text),
        forms=_parse_forms(response.text, final_url),
    )


async def _follow_login_meta_refresh(
    client: httpx.AsyncClient,
    response: httpx.Response,
) -> httpx.Response:
    next_url = _meta_refresh_url(response)
    seen_urls = {str(response.url)}
    while next_url is not None and next_url not in seen_urls:
        seen_urls.add(next_url)
        response = await client.get(next_url)
        next_url = _meta_refresh_url(response)

    return response


def _next_login_url(response: httpx.Response) -> str | None:
    return _meta_refresh_url(response) or _password_url(response)


def _meta_refresh_url(response: httpx.Response) -> str | None:
    tree = HTMLParser(response.text)
    for meta in tree.css("meta"):
        if (meta.attributes.get("http-equiv") or "").lower() != "refresh":
            continue

        content = meta.attributes.get("content") or ""
        match = re.search(r"url=([^;]+)", content, flags=re.IGNORECASE)
        if match:
            return urljoin(str(response.url), match.group(1).strip())

    return None


def _password_url(response: httpx.Response) -> str | None:
    final_url = str(response.url)
    if "/auth/common/password/" in final_url:
        return final_url

    tree = HTMLParser(response.text)
    for link in tree.css("a"):
        href = link.attributes.get("href")
        if href and "/auth/common/password/" in href:
            return urljoin(final_url, href)

    for form in tree.css("form"):
        action = form.attributes.get("action")
        if action and "/auth/common/password/" in action:
            return urljoin(final_url, action)

    return None


def _looks_authenticated(response: httpx.Response) -> bool:
    final_url = str(response.url)
    if "/studis/" in final_url and "student.phtml" in final_url:
        return True

    title = (_parse_title(response.text) or "").lower()
    return "studis" in title and "jednotné přihlášení" not in title


def _cookie_header(cookie_jar: CookieJar) -> str:
    return "; ".join(f"{cookie.name}={cookie.value}" for cookie in cookie_jar)
