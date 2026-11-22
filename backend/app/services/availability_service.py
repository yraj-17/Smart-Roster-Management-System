"""Leaves, unavailability and the comp-off lifecycle.

Every change that affects who can work marks overlapping roster versions STALE,
so they are re-validated (and gaps/suggestions refreshed) on their next read.
The response tells the manager which versions are affected and the window to
re-optimise, so the roster can be repaired without rebuilding it.

Comp-off lifecycle (all transitions audited):
  earn (on publish, holiday work) -> PENDING -> approve -> AVAILABLE (expires after
  COMP_OFF_EXPIRY_DAYS) -> request + approve -> CONSUMED (day becomes COMP_OFF);
  PENDING -> REJECTED; AVAILABLE -> EXPIRED; work removed in a later published
  roster -> REVERSED.  Cancelling an approved request returns the credit.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.errors import Conflict, DomainError, NotFound

from . import audit
from .staleness import mark_stale


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _employee(s: Session, employee_id: int) -> m.Employee:
    e = s.get(m.Employee, employee_id)
    if e is None:
        raise NotFound(f"Employee {employee_id} not found")
    return e


def _change_result(s: Session, obj, stale: list[int], employee_id: int, d1: date, d2: date) -> dict:
    return {
        "item": audit.row_dict(obj),
        "stale_version_ids": stale,
        "reoptimize_hint": {"employee_ids": [employee_id], "date_from": d1.isoformat(), "date_to": d2.isoformat()}
        if stale else None,
    }


# ───────────────────────────── leaves ─────────────────────────────
def create_leave(s: Session, data, actor: str) -> m.Leave:
    emp = _employee(s, data.employee_id)
    if not emp.active:
        raise Conflict("Employee is inactive.")
    overlap = s.scalar(select(m.Leave).where(
        m.Leave.employee_id == emp.id, m.Leave.status.in_(("REQUESTED", "APPROVED")),
        m.Leave.start_date <= data.end_date, m.Leave.end_date >= data.start_date))
    if overlap is not None:
        raise Conflict(f"Overlaps leave #{overlap.id} ({overlap.start_date} to {overlap.end_date}, {overlap.status}).")
    lv = m.Leave(**data.model_dump(), status="REQUESTED")
    s.add(lv)
    s.flush()
    audit.log(s, actor, "leave", lv.id, "request", after=audit.row_dict(lv))
    s.commit()
    return lv


def _get_leave(s: Session, leave_id: int) -> m.Leave:
    lv = s.get(m.Leave, leave_id)
    if lv is None:
        raise NotFound(f"Leave {leave_id} not found")
    return lv


def decide_leave(s: Session, leave_id: int, decision: str, actor: str, reason: str | None) -> dict:
    lv = _get_leave(s, leave_id)
    allowed = {"APPROVED": ("REQUESTED",), "REJECTED": ("REQUESTED",), "CANCELLED": ("REQUESTED", "APPROVED")}
    if lv.status not in allowed[decision]:
        raise Conflict(f"Cannot move a {lv.status} leave to {decision}.")
    was_approved = lv.status == "APPROVED"
    before = lv.status
    lv.status, lv.decided_by, lv.decided_at = decision, actor, _now()
    stale = []
    if decision == "APPROVED" or was_approved:
        stale = mark_stale(s, lv.start_date, lv.end_date)
    audit.log(s, actor, "leave", lv.id, decision.lower(), before={"status": before}, after={"status": decision},
              reason=reason)
    s.commit()
    return _change_result(s, lv, stale, lv.employee_id, lv.start_date, lv.end_date)


# ───────────────────────────── unavailability ─────────────────────────────
def save_unavailability(s: Session, data, actor: str, item_id: int | None = None) -> dict:
    _employee(s, data.employee_id)
    if item_id is None:
        u = m.Unavailability(**data.model_dump())
        s.add(u)
        before = None
    else:
        u = s.get(m.Unavailability, item_id)
        if u is None:
            raise NotFound("Unavailability not found")
        before = audit.row_dict(u)
        stale_old = mark_stale(s, u.start_date, u.end_date)
        for k, v in data.model_dump().items():
            setattr(u, k, v)
    s.flush()
    stale = mark_stale(s, u.start_date, u.end_date)
    if item_id is not None:
        stale = sorted(set(stale) | set(stale_old))
    audit.log(s, actor, "unavailability", u.id, "update" if item_id else "create", before=before,
              after=audit.row_dict(u))
    s.commit()
    return _change_result(s, u, stale, u.employee_id, u.start_date, u.end_date)


def delete_unavailability(s: Session, item_id: int, actor: str) -> dict:
    u = s.get(m.Unavailability, item_id)
    if u is None:
        raise NotFound("Unavailability not found")
    stale = mark_stale(s, u.start_date, u.end_date)
    audit.log(s, actor, "unavailability", u.id, "delete", before=audit.row_dict(u))
    s.delete(u)
    s.commit()
    return {"deleted": item_id, "stale_version_ids": stale}


# ───────────────────────────── comp-offs ─────────────────────────────
def expire_due(s: Session, today: date | None = None) -> int:
    today = today or date.today()
    due = s.scalars(select(m.CompOffCredit).where(m.CompOffCredit.status == "AVAILABLE",
                                                  m.CompOffCredit.expires_on < today)).all()
    for c in due:
        c.status = "EXPIRED"
        audit.log(s, "system", "comp_off_credit", c.id, "expire", before={"status": "AVAILABLE"},
                  after={"status": "EXPIRED"})
    if due:
        s.commit()
    return len(due)


def _credit(s: Session, credit_id: int) -> m.CompOffCredit:
    c = s.get(m.CompOffCredit, credit_id)
    if c is None:
        raise NotFound(f"Comp-off credit {credit_id} not found")
    return c


def grant_credit(s: Session, data, actor: str) -> m.CompOffCredit:
    _employee(s, data.employee_id)
    c = m.CompOffCredit(employee_id=data.employee_id, earned_on=data.earned_on, source="MANUAL",
                        status="AVAILABLE", note=data.note,
                        expires_on=date.today() + timedelta(days=get_settings().comp_off_expiry_days))
    s.add(c)
    s.flush()
    audit.log(s, actor, "comp_off_credit", c.id, "grant", after=audit.row_dict(c))
    s.commit()
    return c


def decide_credit(s: Session, credit_id: int, approve: bool, actor: str, reason: str | None) -> m.CompOffCredit:
    c = _credit(s, credit_id)
    if c.status != "PENDING":
        raise Conflict(f"Only PENDING credits can be decided (this one is {c.status}).")
    if approve:
        c.status = "AVAILABLE"
        c.expires_on = date.today() + timedelta(days=get_settings().comp_off_expiry_days)
    else:
        c.status = "REJECTED"
    audit.log(s, actor, "comp_off_credit", c.id, "approve" if approve else "reject", before={"status": "PENDING"},
              after={"status": c.status, "expires_on": c.expires_on.isoformat() if c.expires_on else None},
              reason=reason)
    s.commit()
    return c


def create_request(s: Session, data, actor: str) -> m.CompOffRequest:
    expire_due(s)
    c = _credit(s, data.credit_id)
    if c.employee_id != data.employee_id:
        raise Conflict("The credit belongs to another employee.")
    if c.status != "AVAILABLE":
        raise Conflict(f"The credit is {c.status}, not AVAILABLE.")
    if c.expires_on and data.date > c.expires_on:
        raise Conflict(f"The credit expires on {c.expires_on}; choose an earlier date.")
    r = m.CompOffRequest(employee_id=data.employee_id, date=data.date, credit_id=c.id, status="REQUESTED")
    s.add(r)
    s.flush()
    audit.log(s, actor, "comp_off_request", r.id, "request", after=audit.row_dict(r))
    s.commit()
    return r


def decide_request(s: Session, request_id: int, decision: str, actor: str, reason: str | None) -> dict:
    r = s.get(m.CompOffRequest, request_id)
    if r is None:
        raise NotFound(f"Comp-off request {request_id} not found")
    allowed = {"APPROVED": ("REQUESTED",), "REJECTED": ("REQUESTED",), "CANCELLED": ("REQUESTED", "APPROVED")}
    if r.status not in allowed[decision]:
        raise Conflict(f"Cannot move a {r.status} request to {decision}.")
    c = s.get(m.CompOffCredit, r.credit_id)
    before = r.status
    stale: list[int] = []
    if decision == "APPROVED":
        if c.status != "AVAILABLE":
            raise Conflict(f"The credit is {c.status}; it cannot be consumed.")
        c.status, c.consumed_on = "CONSUMED", r.date
        stale = mark_stale(s, r.date, r.date)
        audit.log(s, actor, "comp_off_credit", c.id, "consume", before={"status": "AVAILABLE"},
                  after={"status": "CONSUMED", "consumed_on": r.date.isoformat()})
    elif decision == "CANCELLED" and before == "APPROVED":
        c.status = "EXPIRED" if c.expires_on and c.expires_on < date.today() else "AVAILABLE"
        c.consumed_on = None
        stale = mark_stale(s, r.date, r.date)
        audit.log(s, actor, "comp_off_credit", c.id, "restore", before={"status": "CONSUMED"},
                  after={"status": c.status})
    r.status, r.decided_by, r.decided_at = decision, actor, _now()
    audit.log(s, actor, "comp_off_request", r.id, decision.lower(), before={"status": before},
              after={"status": decision}, reason=reason)
    s.commit()
    return _change_result(s, r, stale, r.employee_id, r.date, r.date)


def balance(s: Session, employee_id: int) -> dict:
    _employee(s, employee_id)
    expire_due(s)
    credits = s.scalars(select(m.CompOffCredit).where(m.CompOffCredit.employee_id == employee_id)
                        .order_by(m.CompOffCredit.earned_on)).all()
    by = {}
    for c in credits:
        by[c.status] = by.get(c.status, 0) + 1
    return {"employee_id": employee_id, "available": by.get("AVAILABLE", 0), "pending": by.get("PENDING", 0),
            "by_status": by, "credits": [audit.row_dict(c) for c in credits]}


def validate_range(d1: date, d2: date) -> None:
    if d2 < d1:
        raise DomainError("end date before start date")
