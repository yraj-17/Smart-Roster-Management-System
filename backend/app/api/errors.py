"""Uniform error model: {"error": {"code", "message", "details"}}."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError


from app.errors import Conflict, DomainError, NotFound  # noqa: F401  (re-exported)

# Friendly messages for database constraints that users can realistically hit.
CONSTRAINT_MESSAGES = {
    "ex_assignments_no_overlap": "This employee already has an assignment for that brand-process overlapping "
                                 "these dates. End the existing assignment first (set its effective_to).",
    "uq_roster_duties_no_double_count": "The employee already has a duty for this brand-process on that day.",
    "uq_roster_versions_one_published": "Another version of this month is already published.",
    "fk_roster_duties_entry": "Duties can only exist on a WORK day with the same shift. Remove the day's duties "
                              "before changing its status or shift.",
    "fk_roster_duties_assignment": "The duty does not match an assignment of this employee for this brand-process.",
    "fk_roster_duties_slot": "The duty's shift is not a shift this brand-process runs.",
    "uq_comp_off_requests_active_credit": "This comp-off credit already has an active request.",
}


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        diag = getattr(exc.orig, "diag", None)
        name = getattr(diag, "constraint_name", None) or ""
        msg = CONSTRAINT_MESSAGES.get(name)
        if msg is None:
            if name.startswith("uq_") or "unique" in str(exc.orig).lower():
                msg = "A record with these values already exists."
            elif name.startswith("fk_") or "foreign key" in str(exc.orig).lower():
                msg = "This record is referenced by other data or references a missing record."
            else:
                msg = "The change violates a data integrity rule."
        return _error(409, "integrity_error", msg, {"constraint": name or None})

    @app.exception_handler(DBAPIError)
    async def _dbapi(_: Request, exc: DBAPIError):
        diag = getattr(exc.orig, "diag", None)
        if getattr(exc.orig, "sqlstate", None) == "23514" and diag is not None:  # trigger check_violation
            return _error(409, "integrity_error", diag.message_primary, None)
        raise exc
