from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(".env")


class Settings(BaseSettings):
    base_url: AnyHttpUrl = Field(alias="VUT_BASE_URL")
    username: str | None = Field(default=None, alias="VUT_USERNAME")
    password: str | None = Field(default=None, alias="VUT_PASSWORD")
    session_cookie: str | None = Field(default=None, alias="VUT_SESSION_COOKIE")
    moodle_base_url: AnyHttpUrl = Field(
        default="https://moodle.vut.cz",
        alias="VUT_MOODLE_BASE_URL",
    )
    moodle_access_mode: Literal["auto", "api", "web"] = Field(
        default="auto",
        alias="VUT_MOODLE_ACCESS_MODE",
    )
    moodle_token: str | None = Field(default=None, alias="VUT_MOODLE_TOKEN")
    moodle_session_cookie: str | None = Field(
        default=None,
        alias="VUT_MOODLE_SESSION_COOKIE",
    )
    http_timeout_seconds: float = Field(default=20.0, alias="VUT_HTTP_TIMEOUT_SECONDS")
    cache_path: Path | None = Field(default=None, alias="VUT_CACHE_PATH")
    cache_disabled: bool = Field(default=False, alias="VUT_CACHE_DISABLED")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("cache_path", mode="before")
    @classmethod
    def empty_cache_path_is_default(cls, value: object) -> object:
        if value == "":
            return None
        return value


def load_settings() -> Settings:
    return Settings()


def set_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    replacement = f'{key}="{_escape_env_value(value)}"'

    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)

    path.write_text("\n".join(lines) + "\n")


def _escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
