from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    base_url: AnyHttpUrl = Field(alias="VUT_BASE_URL")
    username: str | None = Field(default=None, alias="VUT_USERNAME")
    password: str | None = Field(default=None, alias="VUT_PASSWORD")
    session_cookie: str | None = Field(default=None, alias="VUT_SESSION_COOKIE")
    http_timeout_seconds: float = Field(default=20.0, alias="VUT_HTTP_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


def load_settings() -> Settings:
    return Settings()
