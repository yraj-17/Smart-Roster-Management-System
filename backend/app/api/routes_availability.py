from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from sqlalchemy import select

from app import models as m
from app import schemas as sc
from app.errors import NotFound
from app.services import availability_service as av

from .deps import DB, Actor

router = APIRouter(prefix="/api", tags=["availability"])


# ── leaves ─────────────────────────────────────────────────────────────────
@router.get("/leaves", response_model=list[sc.LeaveOut])
def list_leaves(db: DB, employee_id: int | None = None, status: str | None = None,
                date_from: date | None = None, date_to: date | None = None):
    q = select(m.Leave)
    if employee_id is not None:
        q = q.where(m.Leave.employee_id == employee_id)
    if status:
        q = q.where(m.Leave.status == status.upper())
    if date_from:
        q = q.where(m.Leave.end_date >= date_from)
    if date_to:
        q = q.where(m.Leave.start_date <= date_to)
    return db.scalars(q.order_by(m.Leave.start_date)).all()


@router.post("/leaves", response_model=sc.LeaveOut, status_code=201)
def request_leave(data: sc.LeaveIn, db: DB, actor: Actor):
    return av.create_leave(db, data, actor)


@router.post("/leaves/{leave_id}/approve")
def approve_leave(leave_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    """Approve; affected roster versions become STALE and the response gives the re-optimise window."""
    return av.decide_leave(db, leave_id, "APPROVED", actor, data.reason if data else None)


@router.post("/leaves/{leave_id}/reject")
def reject_leave(leave_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_leave(db, leave_id, "REJECTED", actor, data.reason if data else None)


@router.post("/leaves/{leave_id}/cancel")
def cancel_leave(leave_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_leave(db, leave_id, "CANCELLED", actor, data.reason if data else None)


# ── unavailability ─────────────────────────────────────────────────────────
@router.get("/unavailability", response_model=list[sc.UnavailabilityOut])
def list_unavailability(db: DB, employee_id: int | None = None):
    q = select(m.Unavailability)
    if employee_id is not None:
        q = q.where(m.Unavailability.employee_id == employee_id)
    return db.scalars(q.order_by(m.Unavailability.start_date)).all()


@router.post("/unavailability", status_code=201)
def create_unavailability(data: sc.UnavailabilityIn, db: DB, actor: Actor):
    return av.save_unavailability(db, data, actor)


@router.put("/unavailability/{item_id}")
def update_unavailability(item_id: int, data: sc.UnavailabilityIn, db: DB, actor: Actor):
    return av.save_unavailability(db, data, actor, item_id)


@router.delete("/unavailability/{item_id}")
def delete_unavailability(item_id: int, db: DB, actor: Actor):
    return av.delete_unavailability(db, item_id, actor)


# ── comp-offs ──────────────────────────────────────────────────────────────
@router.get("/comp-offs/credits", response_model=list[sc.CompOffCreditOut])
def list_credits(db: DB, employee_id: int | None = None, status: str | None = None):
    av.expire_due(db)
    q = select(m.CompOffCredit)
    if employee_id is not None:
        q = q.where(m.CompOffCredit.employee_id == employee_id)
    if status:
        q = q.where(m.CompOffCredit.status == status.upper())
    return db.scalars(q.order_by(m.CompOffCredit.earned_on)).all()


@router.post("/comp-offs/credits", response_model=sc.CompOffCreditOut, status_code=201)
def grant_credit(data: sc.CompOffGrantIn, db: DB, actor: Actor):
    """Manually grant an (approved) comp-off credit."""
    return av.grant_credit(db, data, actor)


@router.post("/comp-offs/credits/{credit_id}/approve", response_model=sc.CompOffCreditOut)
def approve_credit(credit_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_credit(db, credit_id, True, actor, data.reason if data else None)


@router.post("/comp-offs/credits/{credit_id}/reject", response_model=sc.CompOffCreditOut)
def reject_credit(credit_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_credit(db, credit_id, False, actor, data.reason if data else None)


@router.get("/comp-offs/requests", response_model=list[sc.CompOffRequestOut])
def list_requests(db: DB, employee_id: int | None = None, status: str | None = None):
    q = select(m.CompOffRequest)
    if employee_id is not None:
        q = q.where(m.CompOffRequest.employee_id == employee_id)
    if status:
        q = q.where(m.CompOffRequest.status == status.upper())
    return db.scalars(q.order_by(m.CompOffRequest.date)).all()


@router.post("/comp-offs/requests", response_model=sc.CompOffRequestOut, status_code=201)
def create_request(data: sc.CompOffRequestIn, db: DB, actor: Actor):
    return av.create_request(db, data, actor)


@router.post("/comp-offs/requests/{request_id}/approve")
def approve_request(request_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_request(db, request_id, "APPROVED", actor, data.reason if data else None)


@router.post("/comp-offs/requests/{request_id}/reject")
def reject_request(request_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_request(db, request_id, "REJECTED", actor, data.reason if data else None)


@router.post("/comp-offs/requests/{request_id}/cancel")
def cancel_request(request_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return av.decide_request(db, request_id, "CANCELLED", actor, data.reason if data else None)


@router.get("/employees/{employee_id}/comp-off-balance")
def comp_off_balance(employee_id: int, db: DB):
    if db.get(m.Employee, employee_id) is None:
        raise NotFound("Employee not found")
    return av.balance(db, employee_id)
