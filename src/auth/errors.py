"""Authentication error type shared by every module in the ``auth`` package."""


class AuthError(Exception):
    """Raised for any sign-in or token failure with a user-safe message."""
