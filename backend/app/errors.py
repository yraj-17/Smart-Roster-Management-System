"""Domain errors raised by services and mapped to HTTP responses in app.api.errors."""
from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict | list | None = None, code: str | None = None):
        super().__init__(message)
        self.message, self.details = message, details
        if code:
            self.code = code


class NotFound(DomainError):
    status_code, code = 404, "not_found"


class Conflict(DomainError):
    status_code, code = 409, "conflict"
