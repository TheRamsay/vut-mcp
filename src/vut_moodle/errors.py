"""Typed errors raised by the Moodle integration."""


class MoodleError(Exception):
    """Base error for Moodle client failures."""


class MoodleConfigurationError(MoodleError):
    """Raised when Moodle configuration is incomplete or invalid."""


class MoodleAuthError(MoodleError):
    """Raised when Moodle authentication is missing or invalid."""


class MoodleApiError(MoodleError):
    """Raised when a Moodle web-service request fails."""

    def __init__(self, function: str, message: str) -> None:
        super().__init__(f"Moodle API {function}: {message}")
        self.function = function


class MoodleDataError(MoodleError):
    """Raised when Moodle data cannot be parsed into domain models."""


class MoodleContentError(MoodleError):
    """Raised when Moodle attachment content is unsafe or unsupported."""
