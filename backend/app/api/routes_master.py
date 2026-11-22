"""Master data: policies, pods, employees, processes, brands, shifts, brand-processes,
coverage slots, coverage overrides, assignments, holiday calendars and holidays.

Changes that can affect scheduling are audited and mark live roster versions STALE.
Entities referenced by roster history are deactivated rather than deleted.
"""

from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Body, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import schemas as sc
from app.errors import Conflict, DomainError, NotFound
from app.services import audit
from app.services.staleness import mark_stale

from .deps import DB, Actor

router = APIRouter(prefix="/api")


def crud(prefix: str, model, In, Out, entity: str, *, soft_delete: bool = False, affects_schedule: bool = True,
         filters: tuple[str, ...] = (), before_save: Callable[[Session, object, object], None] | None = None,
         stale_range: Callable[[object], tuple[date, date] | None] | None = None):
    def _get(db: Session, item_id: int):
        obj = db.get(model, item_id)
        if obj is None:
            raise NotFound(f"{entity} {item_id} not found")
        return obj

    def _stale(db: Session, obj) -> None:
        if not affects_schedule:
            return
        rng = stale_range(obj) if stale_range else None
        mark_stale(db, *rng) if rng else mark_stale(db)

    @router.get(prefix, response_model=list[Out], tags=[entity], name=f"list_{entity}")
    def list_items(request: Request, db: DB):
        q = select(model)
        for f in filters:
            raw = request.query_params.get(f)
            if raw is None:
                continue
            col = getattr(model, f)
            try:
                val = (raw.lower() == "true") if col.type.python_type is bool else col.type.python_type(raw)
            except (ValueError, TypeError):
                raise DomainError(f"invalid value for {f}")
            q = q.where(col == val)
        return db.scalars(q.order_by(model.id)).all()

    @router.get(prefix + "/{item_id}", response_model=Out, tags=[entity], name=f"get_{entity}")
    def get_item(item_id: int, db: DB):
        return _get(db, item_id)

    @router.post(prefix, response_model=Out, status_code=201, tags=[entity], name=f"create_{entity}")
    def create_item(data: In, db: DB, actor: Actor):
        obj = model(**data.model_dump())
        if before_save:
            before_save(db, obj, data)
        db.add(obj)
        db.flush()
        audit.log(db, actor, entity, obj.id, "create", after=audit.row_dict(obj))
        _stale(db, obj)
        db.commit()
        db.refresh(obj)
        return obj

    @router.put(prefix + "/{item_id}", response_model=Out, tags=[entity], name=f"update_{entity}")
    def update_item(item_id: int, data: In, db: DB, actor: Actor):
        obj = _get(db, item_id)
        before = audit.row_dict(obj)
        if stale_range:
            _stale(db, obj)  # old range
        for k, v in data.model_dump().items():
            setattr(obj, k, v)
        if before_save:
            before_save(db, obj, data)
        db.flush()
        audit.log(db, actor, entity, obj.id, "update", before=before, after=audit.row_dict(obj))
        _stale(db, obj)
        db.commit()
        db.refresh(obj)
        return obj

    @router.delete(prefix + "/{item_id}", tags=[entity], name=f"delete_{entity}")
    def delete_item(item_id: int, db: DB, actor: Actor):
        obj = _get(db, item_id)
        before = audit.row_dict(obj)
        _stale(db, obj)
        if soft_delete:
            obj.active = False
            audit.log(db, actor, entity, obj.id, "deactivate", before=before, after={"active": False})
            db.commit()
            return {"id": item_id, "deactivated": True}
        audit.log(db, actor, entity, obj.id, "delete", before=before)
        db.delete(obj)
        db.commit()
        return {"id": item_id, "deleted": True}


# ── hooks ──────────────────────────────────────────────────────────────────
def _pod_lead_check(db: Session, pod: m.Pod, data) -> None:
    if data.lead_employee_id is not None:
        lead = db.get(m.Employee, data.lead_employee_id)
        if lead is None:
            raise NotFound("Lead employee not found")
        if pod.id is not None and lead.pod_id != pod.id:
            raise Conflict("A pod lead must be a member of the pod.")


def _single_default(db: Session, cal: m.HolidayCalendar, data) -> None:
    if data.is_default:
        for other in db.scalars(select(m.HolidayCalendar).where(m.HolidayCalendar.is_default)):
            if other is not cal:
                other.is_default = False
        db.flush()


def _assignment_check(db: Session, a: m.Assignment, data) -> None:
    if a.shift_id is not None:
        slot = db.scalar(select(m.BrandProcessShift).where(
            m.BrandProcessShift.brand_process_id == a.brand_process_id, m.BrandProcessShift.shift_id == a.shift_id))
        if slot is None:
            raise Conflict("The brand-process does not run the shift this assignment is restricted to.")


crud("/weekly-off-policies", m.WeeklyOffPolicy, sc.WeeklyOffPolicyIn, sc.WeeklyOffPolicyOut, "weekly_off_policy")
crud("/pods", m.Pod, sc.PodIn, sc.PodOut, "pod", soft_delete=True, affects_schedule=False,
     before_save=_pod_lead_check, filters=("active",))
crud("/processes", m.Process, sc.ProcessIn, sc.ProcessOut, "process", soft_delete=True, filters=("active",))
crud("/brands", m.Brand, sc.BrandIn, sc.BrandOut, "brand", soft_delete=True, filters=("active",))
crud("/shifts", m.Shift, sc.ShiftIn, sc.ShiftOut, "shift")
crud("/brand-processes", m.BrandProcess, sc.BrandProcessIn, sc.BrandProcessOut, "brand_process",
     soft_delete=True, filters=("brand_id", "process_id", "active"))
crud("/slots", m.BrandProcessShift, sc.SlotIn, sc.SlotOut, "brand_process_shift", soft_delete=True,
     filters=("brand_process_id", "shift_id", "active"))
crud("/coverage-requirements", m.CoverageRequirement, sc.CoverageRequirementIn, sc.CoverageRequirementOut,
     "coverage_requirement", filters=("brand_process_shift_id",),
     stale_range=lambda o: (o.specific_date, o.specific_date) if o.specific_date else None)
crud("/assignments", m.Assignment, sc.AssignmentIn, sc.AssignmentOut, "assignment",
     filters=("employee_id", "brand_process_id", "role"), before_save=_assignment_check)
crud("/holiday-calendars", m.HolidayCalendar, sc.HolidayCalendarIn, sc.HolidayCalendarOut, "holiday_calendar",
     before_save=_single_default)


# ── employees (nested off-day preferences) ─────────────────────────────────
def _emp_dump(e: m.Employee) -> dict:
    d = audit.row_dict(e)
    d["off_days"] = [{"day_of_week": o.day_of_week, "kind": o.kind, "priority": o.priority} for o in e.off_days]
    return d


@router.get("/employees", response_model=list[sc.EmployeeOut], tags=["employee"])
def list_employees(db: DB, pod_id: int | None = None, active: bool | None = None):
    q = select(m.Employee)
    if pod_id is not None:
        q = q.where(m.Employee.pod_id == pod_id)
    if active is not None:
        q = q.where(m.Employee.active == active)
    return db.scalars(q.order_by(m.Employee.code)).all()


@router.get("/employees/{employee_id}", response_model=sc.EmployeeOut, tags=["employee"])
def get_employee(employee_id: int, db: DB):
    e = db.get(m.Employee, employee_id)
    if e is None:
        raise NotFound("Employee not found")
    return e


def _apply_employee(e: m.Employee, data: sc.EmployeeIn) -> None:
    for k, v in data.model_dump(exclude={"off_days"}).items():
        setattr(e, k, v)
    e.off_days = [m.EmployeeOffDay(day_of_week=o.day_of_week, kind=o.kind, priority=o.priority)
                  for o in data.off_days]


@router.post("/employees", response_model=sc.EmployeeOut, status_code=201, tags=["employee"])
def create_employee(data: sc.EmployeeIn, db: DB, actor: Actor):
    e = m.Employee()
    _apply_employee(e, data)
    db.add(e)
    db.flush()
    audit.log(db, actor, "employee", e.id, "create", after=_emp_dump(e))
    mark_stale(db)
    db.commit()
    db.refresh(e)
    return e


@router.put("/employees/{employee_id}", response_model=sc.EmployeeOut, tags=["employee"])
def update_employee(employee_id: int, data: sc.EmployeeIn, db: DB, actor: Actor):
    e = db.get(m.Employee, employee_id)
    if e is None:
        raise NotFound("Employee not found")
    before = _emp_dump(e)
    e.off_days.clear()
    db.flush()
    _apply_employee(e, data)
    db.flush()
    audit.log(db, actor, "employee", e.id, "update", before=before, after=_emp_dump(e))
    mark_stale(db)
    db.commit()
    db.refresh(e)
    return e


@router.delete("/employees/{employee_id}", tags=["employee"])
def deactivate_employee(employee_id: int, db: DB, actor: Actor):
    e = db.get(m.Employee, employee_id)
    if e is None:
        raise NotFound("Employee not found")
    e.active = False
    audit.log(db, actor, "employee", e.id, "deactivate", before={"active": True}, after={"active": False})
    mark_stale(db)
    db.commit()
    return {"id": employee_id, "deactivated": True}


# ── holidays (per calendar) ────────────────────────────────────────────────
def _calendar(db: Session, cal_id: int) -> m.HolidayCalendar:
    c = db.get(m.HolidayCalendar, cal_id)
    if c is None:
        raise NotFound("Holiday calendar not found")
    return c


@router.get("/holiday-calendars/{cal_id}/holidays", response_model=list[sc.HolidayOut], tags=["holiday"])
def list_holidays(cal_id: int, db: DB, year: int | None = None):
    _calendar(db, cal_id)
    q = select(m.PublicHoliday).where(m.PublicHoliday.calendar_id == cal_id)
    if year:
        q = q.where(m.PublicHoliday.date.between(date(year, 1, 1), date(year, 12, 31)))
    return db.scalars(q.order_by(m.PublicHoliday.date)).all()


@router.post("/holiday-calendars/{cal_id}/holidays", response_model=sc.HolidayOut, status_code=201, tags=["holiday"])
def create_holiday(cal_id: int, data: sc.HolidayIn, db: DB, actor: Actor):
    _calendar(db, cal_id)
    h = m.PublicHoliday(calendar_id=cal_id, **data.model_dump())
    db.add(h)
    db.flush()
    audit.log(db, actor, "public_holiday", h.id, "create", after=audit.row_dict(h))
    mark_stale(db, h.date, h.date)
    db.commit()
    db.refresh(h)
    return h


@router.put("/holidays/{holiday_id}", response_model=sc.HolidayOut, tags=["holiday"])
def update_holiday(holiday_id: int, data: sc.HolidayIn, db: DB, actor: Actor):
    h = db.get(m.PublicHoliday, holiday_id)
    if h is None:
        raise NotFound("Holiday not found")
    before = audit.row_dict(h)
    mark_stale(db, h.date, h.date)
    for k, v in data.model_dump().items():
        setattr(h, k, v)
    db.flush()
    mark_stale(db, h.date, h.date)
    audit.log(db, actor, "public_holiday", h.id, "update", before=before, after=audit.row_dict(h))
    db.commit()
    db.refresh(h)
    return h


@router.delete("/holidays/{holiday_id}", tags=["holiday"])
def delete_holiday(holiday_id: int, db: DB, actor: Actor):
    h = db.get(m.PublicHoliday, holiday_id)
    if h is None:
        raise NotFound("Holiday not found")
    mark_stale(db, h.date, h.date)
    audit.log(db, actor, "public_holiday", h.id, "delete", before=audit.row_dict(h))
    db.delete(h)
    db.commit()
    return {"id": holiday_id, "deleted": True}


@router.post("/holiday-calendars/{cal_id}/holidays/import", tags=["holiday"])
def import_holidays(cal_id: int, db: DB, actor: Actor,
                    body: str = Body(..., media_type="text/csv",
                                     description="CSV lines: date,name[,kind]  (header optional)")):
    """Upsert holidays from CSV text (date as YYYY-MM-DD)."""
    _calendar(db, cal_id)
    created = updated = 0
    errors = []
    dates = []
    for n, line in enumerate(body.splitlines(), start=1):
        parts = [p.strip() for p in line.split(",")]
        if not line.strip() or parts[0].lower() == "date":
            continue
        try:
            d = date.fromisoformat(parts[0])
            data = sc.HolidayIn(date=d, name=parts[1], kind=(parts[2] if len(parts) > 2 and parts[2] else "NATIONAL"))
        except Exception as exc:  # report every bad line instead of failing on the first
            errors.append({"line": n, "error": str(exc).splitlines()[0]})
            continue
        h = db.scalar(select(m.PublicHoliday).where(m.PublicHoliday.calendar_id == cal_id,
                                                    m.PublicHoliday.date == d))
        if h is None:
            db.add(m.PublicHoliday(calendar_id=cal_id, **data.model_dump()))
            created += 1
        else:
            h.name, h.kind = data.name, data.kind
            updated += 1
        dates.append(d)
    if errors:
        db.rollback()
        raise DomainError("CSV contains invalid lines; nothing was imported.", details=errors)
    stale = mark_stale(db, min(dates), max(dates)) if dates else []
    audit.log(db, actor, "holiday_calendar", cal_id, "import", after={"created": created, "updated": updated})
    db.commit()
    return {"created": created, "updated": updated, "stale_version_ids": stale}
