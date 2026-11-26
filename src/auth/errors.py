"""Authentication error type shared by every module in the ``auth`` package."""


class AuthError(Exception):
    """Raised for any sign-in or token failure with a user-safe message."""

    def __init__(self, message: str, rejected: bool = False, status: int = 0, logged: str = "") -> None:
        super().__init__(message)
        self.status = status   # the HTTP status, when the message quotes what the token endpoint said
        self.logged = logged   # what a log says instead, when the message quotes words from outside (the sign-in redirect's description)
        self.rejected = rejected   # True when Autodesk refused the token itself (the session is gone); False for a failure that may pass

    @property
    def log_text(self) -> str:
        """What a log says of this error (``RedactingFormatter`` uses it in place of the message): ``logged`` when there is one, else the status
        only when the message quotes what the token endpoint answered. A message made here is its own text."""
        return self.logged or (f"Token request failed ({self.status})" if self.status else str(self))
