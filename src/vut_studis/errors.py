class StudisError(Exception):
    """Base error for Studis client failures."""


class StudisAuthError(StudisError):
    """Raised when Studis authentication is missing or invalid."""


class StudisParseError(StudisError):
    """Raised when Studis data cannot be parsed into domain models."""
