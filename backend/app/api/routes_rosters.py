from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from app import models as m
from app import schemas as sc
from app.errors import NotFound
from app.services import dashboard_service
from app.services import roster_service as rs
from app.services.validation_service import ensure_fresh, revalidate

from .deps import DB, Actor

router = APIRouter(prefix="/api")


# ── plans & versions ───────────────────────────────────────────────────────
@router.get("/roster-plans", tags=["roster"])
def list_plans(db: DB):
    rows = db.execute(select(m.RosterPlan, func.count(m.RosterVersion.id))
                      .outerjoin(m.RosterVersion).group_by(m.RosterPlan.id)
                      .order_by(m.RosterPlan.year.desc(), m.RosterPlan.month.desc())).all()
    out = []
    for plan, n in rows:
        pub = db.scalar(select(m.RosterVersion).where(m.RosterVersion.plan_id == plan.id,
                                                      m.RosterVersion.status == "PUBLISHED"))
        out.append({"id": plan.id, "year": plan.year, "month": plan.month, "versions": n,
                    "published_version_id": pub.id if pub else None})
    return out


@router.get("/roster-plans/{year}/{month}/versions", tags=["roster"])
def list_versions(year: int, month: int, db: DB):
    vs = db.scalars(select(m.RosterVersion).join(m.RosterPlan)
                    .where(m.RosterPlan.year == year, m.RosterPlan.month == month)
                    .order_by(m.RosterVersion.version_no)).all()
    return [rs.version_dict(v) for v in vs]


@router.post("/roster-plans/{year}/{month}/generate", status_code=201, tags=["roster"])
def generate(year: int, month: int, db: DB, actor: Actor, data: sc.GenerateIn | None = None):
    """Run the solver for the whole month and store the result as a new DRAFT version."""
    v = rs.generate_version(db, year, month, actor, data.notes if data else None)
    return rs.version_dict(v)


@router.get("/versions/{version_id}", tags=["roster"])
def get_version(version_id: int, db: DB):
    v = rs.get_version(db, version_id)
    ensure_fresh(db, v)
    return rs.version_dict(v)


@router.get("/versions/{version_id}/roster", tags=["roster"])
def roster_view(version_id: int, db: DB, view: str = Query("company", pattern="^(company|pod|brand|process|employee)$"),
                ref_id: int | None = None):
    return rs.roster_view(db, rs.get_version(db, version_id), view, ref_id)


@router.get("/versions/{version_id}/coverage", tags=["roster"])
def coverage(version_id: int, db: DB):
    return rs.roster_view(db, rs.get_version(db, version_id), "company", None)["coverage"]


@router.get("/versions/{version_id}/days/{day}", tags=["roster"])
def day(version_id: int, day: date, db: DB):
    return rs.day_view(db, rs.get_version(db, version_id), day)


@router.get("/versions/{version_id}/duties", tags=["roster"])
def duties(version_id: int, db: DB, day: date | None = None, employee_id: int | None = None,
           brand_process_id: int | None = None):
    rs.get_version(db, version_id)
    q = select(m.RosterDuty).where(m.RosterDuty.version_id == version_id)
    if day:
        q = q.where(m.RosterDuty.date == day)
    if employee_id:
        q = q.where(m.RosterDuty.employee_id == employee_id)
    if brand_process_id:
        q = q.where(m.RosterDuty.brand_process_id == brand_process_id)
    lk = rs.Lookups(db)
    return [{**rs.audit.row_dict(d), **lk.slot_info(d.brand_process_shift_id)}
            for d in db.scalars(q.order_by(m.RosterDuty.date, m.RosterDuty.employee_id))]


@router.put("/versions/{version_id}/entries/{entry_id}", tags=["roster-edit"])
def edit_day(version_id: int, entry_id: int, data: sc.DayEditIn, db: DB, actor: Actor):
    """Replace an employee-day (status, shift, full duty set). Validated; re-validates the version."""
    v = rs.get_version(db, version_id)
    return rs.edit_day(db, v, entry_id, data.status, data.shift_id, data.slot_ids, data.note, actor)


@router.post("/versions/{version_id}/duties", status_code=201, tags=["roster-edit"])
def add_duty(version_id: int, data: sc.DutyIn, db: DB, actor: Actor):
    v = rs.get_version(db, version_id)
    return rs.add_duty(db, v, data.employee_id, data.date, data.brand_process_shift_id, actor)


@router.delete("/versions/{version_id}/duties/{duty_id}", tags=["roster-edit"])
def remove_duty(version_id: int, duty_id: int, db: DB, actor: Actor):
    return rs.remove_duty(db, rs.get_version(db, version_id), duty_id, actor)


@router.post("/versions/{version_id}/validate", tags=["roster"])
def validate_version(version_id: int, db: DB):
    v = rs.get_version(db, version_id)
    revalidate(db, v)
    db.commit()
    return rs.version_dict(v)


@router.post("/versions/{version_id}/reoptimize", status_code=201, tags=["roster-edit"])
def reoptimize(version_id: int, data: sc.ReoptimizeIn, db: DB, actor: Actor):
    """Re-plan only [date_from, date_to] for the affected scope; creates a new draft and returns the diff."""
    v = rs.get_version(db, version_id)
    return rs.reoptimize(db, v, data.date_from, data.date_to, data.employee_ids, data.whole_window,
                         data.override_manual_entry_ids, actor, data.reason)


@router.post("/versions/{version_id}/clone", status_code=201, tags=["roster-edit"])
def clone(version_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return rs.version_dict(rs.clone_version(db, rs.get_version(db, version_id), actor, data.reason if data else None))


@router.post("/versions/{version_id}/publish", tags=["roster"])
def publish(version_id: int, db: DB, actor: Actor, data: sc.DecisionIn | None = None):
    return rs.publish(db, rs.get_version(db, version_id), actor, data.reason if data else None)


@router.post("/versions/{version_id}/archive", tags=["roster"])
def archive(version_id: int, db: DB, actor: Actor):
    return rs.version_dict(rs.archive(db, rs.get_version(db, version_id), actor))


@router.get("/versions/{a}/diff/{b}", tags=["roster"])
def diff(a: int, b: int, db: DB):
    return rs.diff_versions(db, rs.get_version(db, a), rs.get_version(db, b))


@router.get("/versions/{version_id}/export.csv", response_class=PlainTextResponse, tags=["roster"])
def export(version_id: int, db: DB):
    v = rs.get_version(db, version_id)
    name = f"roster-{v.plan.year}-{v.plan.month:02d}-v{v.version_no}.csv"
    return PlainTextResponse(rs.export_csv(db, v), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── conflicts ──────────────────────────────────────────────────────────────
@router.get("/versions/{version_id}/conflicts", response_model=list[sc.ConflictOut], tags=["conflict"])
def list_conflicts(version_id: int, db: DB, status: str | None = None, severity: str | None = None,
                   category: str | None = None, type: str | None = None, day: date | None = None,
                   employee_id: int | None = None):
    v = rs.get_version(db, version_id)
    ensure_fresh(db, v)
    q = select(m.RosterConflict).where(m.RosterConflict.version_id == version_id)
    for col, val in ((m.RosterConflict.status, status), (m.RosterConflict.severity, severity),
                     (m.RosterConflict.category, category), (m.RosterConflict.type, type)):
        if val:
            q = q.where(col == val.upper())
    if day:
        q = q.where(m.RosterConflict.date == day)
    if employee_id:
        q = q.where(m.RosterConflict.employee_id == employee_id)
    return db.scalars(q.order_by(m.RosterConflict.severity, m.RosterConflict.date.nulls_last(),
                                 m.RosterConflict.id)).all()


def _conflict(db, conflict_id: int) -> m.RosterConflict:
    c = db.get(m.RosterConflict, conflict_id)
    if c is None:
        raise NotFound("Conflict not found")
    return c


@router.get("/conflicts/{conflict_id}", response_model=sc.ConflictOut, tags=["conflict"])
def get_conflict(conflict_id: int, db: DB):
    return _conflict(db, conflict_id)


@router.get("/conflicts/{conflict_id}/suggestions", tags=["conflict"])
def suggestions(conflict_id: int, db: DB, limit: int = Query(5, ge=1, le=20)):
    from app.services.validation_service import suggestion_json
    return [suggestion_json(x) for x in rs.fresh_suggestions(db, _conflict(db, conflict_id), limit)]


@router.post("/conflicts/{conflict_id}/apply-suggestion", tags=["conflict"])
def apply_suggestion(conflict_id: int, data: sc.ApplySuggestionIn, db: DB, actor: Actor):
    return rs.apply_suggestion(db, _conflict(db, conflict_id), data.employee_id, data.action, actor)


@router.post("/conflicts/{conflict_id}/acknowledge", response_model=sc.ConflictOut, tags=["conflict"])
def acknowledge(conflict_id: int, data: sc.AcknowledgeIn, db: DB, actor: Actor):
    return rs.acknowledge(db, _conflict(db, conflict_id), data.reason, actor)


# ── change impact, audit, dashboard ────────────────────────────────────────
@router.post("/impact-preview", tags=["change"])
def impact_preview(data: sc.ImpactIn, db: DB):
    """Read-only what-if: which gaps open if this employee is unavailable on these dates, and who could cover."""
    return rs.impact_preview(db, data.employee_id, data.date_from, data.date_to)


@router.get("/audit-log", response_model=list[sc.AuditOut], tags=["audit"])
def audit_log(db: DB, entity_type: str | None = None, entity_id: int | None = None, version_id: int | None = None,
              limit: int = Query(100, ge=1, le=1000)):
    q = select(m.AuditLog)
    if entity_type:
        q = q.where(m.AuditLog.entity_type == entity_type)
    if entity_id is not None:
        q = q.where(m.AuditLog.entity_id == entity_id)
    if version_id is not None:
        q = q.where(m.AuditLog.version_id == version_id)
    return db.scalars(q.order_by(m.AuditLog.id.desc()).limit(limit)).all()


@router.get("/dashboard/summary", tags=["dashboard"])
def dashboard(db: DB, year: int = Query(ge=2000, le=2100), month: int = Query(ge=1, le=12)):
    return dashboard_service.summary(db, year, month)
