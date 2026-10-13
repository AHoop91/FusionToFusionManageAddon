"""Authentication error type shared by every module in the ``auth`` package."""


class AuthError(Exception):
    """Raised for any sign-in or token failure with a user-safe message."""

    def __init__(self, message: str, rejected: bool = False) -> None:
        super().__init__(message)
        self.rejected = rejected   # True when Autodesk refused the token itself (the session is gone); False for a failure that may pass
