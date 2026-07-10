"""Constrained optional Moodle REST adapter."""

from collections.abc import Mapping

import httpx

from vut_moodle.errors import MoodleApiError
from vut_studis.config import Settings


class MoodleApi:
    def __init__(self, settings: Settings) -> None:
        if not settings.moodle_token:
            raise ValueError("A Moodle API token is required to create MoodleApi.")
        self.settings = settings
        self.token = settings.moodle_token

    async def call(self, function: str, **params: object) -> object:
        async with httpx.AsyncClient(
            base_url=str(self.settings.moodle_base_url),
            timeout=self.settings.http_timeout_seconds,
        ) as client:
            response = await client.post(
                "/webservice/rest/server.php",
                data={
                    "wstoken": self.token,
                    "wsfunction": function,
                    "moodlewsrestformat": "json",
                    **flatten_moodle_params(params),
                },
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as error:
            raise MoodleApiError(function, "Moodle returned an invalid JSON response.") from error
        if not isinstance(payload, (dict, list)):
            raise MoodleApiError(function, "Moodle returned an invalid API payload.")
        if isinstance(payload, dict) and "exception" in payload:
            message = payload.get("message") or payload["exception"]
            raise MoodleApiError(function, str(message))
        return payload

    async def get_site_info(self) -> dict[str, object]:
        return _as_mapping(
            await self.call("core_webservice_get_site_info"),
            "core_webservice_get_site_info",
        )

    async def get_user_courses(self, user_id: int) -> list[dict[str, object]]:
        return _as_mappings(
            await self.call("core_enrol_get_users_courses", userid=user_id),
            "core_enrol_get_users_courses",
        )

    async def get_course_contents(self, course_id: int) -> list[dict[str, object]]:
        return _as_mappings(
            await self.call("core_course_get_contents", courseid=course_id),
            "core_course_get_contents",
        )

    async def get_assignments(self, course_ids: list[int]) -> dict[str, object]:
        return _as_mapping(
            await self.call("mod_assign_get_assignments", courseids=course_ids),
            "mod_assign_get_assignments",
        )


def flatten_moodle_params(params: Mapping[str, object]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for key, value in params.items():
        if isinstance(value, list):
            flattened.update({f"{key}[{index}]": str(item) for index, item in enumerate(value)})
        else:
            flattened[key] = str(value)
    return flattened


def _as_mapping(payload: object, function: str) -> dict[str, object]:
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    raise MoodleApiError(function, "Moodle returned an unexpected API payload.")


def _as_mappings(payload: object, function: str) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise MoodleApiError(function, "Moodle returned an unexpected API payload.")
    result: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise MoodleApiError(function, "Moodle returned an unexpected API payload.")
        result.append({str(key): value for key, value in item.items()})
    return result
