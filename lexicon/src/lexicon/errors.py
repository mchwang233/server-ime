"""Stable error codes for lexicon data, user data and engine data access."""


class LexiconError(Exception):
    """A failure that callers can report without guessing at the cause.

    ``code`` is part of the documented interface; see lexicon/format/README.md.
    ``details`` is JSON-serialisable and never contains user text unless the
    caller supplied it.
    """

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}

    def to_dict(self):
        payload = {"ok": False, "error": {"code": self.code, "message": self.message}}
        if self.details:
            payload["error"]["details"] = self.details
        return payload

    def __str__(self):
        return f"{self.code}: {self.message}"
