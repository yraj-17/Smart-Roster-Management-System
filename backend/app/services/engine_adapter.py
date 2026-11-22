"""Bridge between the database and the pure scheduling engine.

load_problem()     DB rows  -> engine Problem (one month)
load_roster()      a stored version -> engine Roster
persist_outcome()  engine Outcome -> new roster_versions row (+ entries, duties,
                   coverage, conflicts, audit) in ONE transaction
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import models as m
from app.config import get_settings
from app.scheduling import Outcome
from app.scheduling import types as t


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, _cal.monthrange(year, month)[1])


# ───────────────────────────── load ─────────────────────────────
def load_problem(s: Session, year: int, month: int) -> t.Problem:
    first, last = month_bounds(year, month)
    look_from = first - timedelta(days=14)
    cfg = get_settings()

    employees = s.scalars(select(m.Employee).where(m.Employee.active)
                          .options(selectinload(m.Employee.policy), selectinload(m.Employee.off_days))).all()
    emps = [
        t.Employee(
            id=e.id, code=e.code, name=e.name, pod_id=e.pod_id,
            policy=t.OffPolicy(e.policy.min_offs_per_week, e.policy.max_consecutive_work_days,
                               e.policy.min_rest_hours, e.policy.holidays_count_as_rest),
            holiday_calendar_id=e.holiday_calendar_id,
            max_daily_load_pct=e.max_daily_load_pct, backup_stretch_pct=e.backup_stretch_pct,
            fixed_off_days=frozenset(o.day_of_week for o in e.off_days if o.kind == "FIXED"),
            preferred_off_days=tuple((o.day_of_week, o.priority) for o in e.off_days if o.kind == "PREFERRED"),
        )
        for e in employees
    ]
    shifts = [t.Shift(x.id, x.code, x.start_time, x.end_time) for x in s.scalars(select(m.Shift))]

    rows = s.execute(select(m.BrandProcess, m.Brand, m.Process)
                     .join(m.Brand, m.Brand.id == m.BrandProcess.brand_id)
                     .join(m.Process, m.Process.id == m.BrandProcess.process_id)).all()
    bps = [t.BrandProcess(bp.id, b.id, b.name, p.code, bp.operating_days_mask, bp.operates_on_holidays,
                          b.holiday_calendar_id, bp.active and b.active and p.active) for bp, b, p in rows]
    slots = [t.Slot(x.id, x.brand_process_id, x.shift_id, x.default_min_staff, x.active)
             for x in s.scalars(select(m.BrandProcessShift))]
    overrides = [t.CoverageOverride(x.brand_process_shift_id, x.min_staff, x.day_of_week, x.specific_date)
                 for x in s.scalars(select(m.CoverageRequirement).where(
                     (m.CoverageRequirement.specific_date.is_(None))
                     | m.CoverageRequirement.specific_date.between(first, last)))]
    assignments = [
        t.Assignment(a.id, a.employee_id, a.brand_process_id, t.Role(a.role), a.load_pct,
                     a.effective_from, a.effective_to, a.shift_id)
        for a in s.scalars(select(m.Assignment).where(
            m.Assignment.effective_from <= last,
            (m.Assignment.effective_to.is_(None)) | (m.Assignment.effective_to >= first)))
    ]

    absences: list[t.Absence] = []
    for lv in s.scalars(select(m.Leave).where(m.Leave.status == "APPROVED", m.Leave.start_date <= last,
                                              m.Leave.end_date >= look_from)):
        absences.append(t.Absence(lv.employee_id, lv.start_date, lv.end_date, t.AbsenceKind.LEAVE, lv.reason or ""))
    for u in s.scalars(select(m.Unavailability).where(m.Unavailability.start_date <= last,
                                                      m.Unavailability.end_date >= look_from)):
        absences.append(t.Absence(u.employee_id, u.start_date, u.end_date, t.AbsenceKind.UNAVAILABLE, u.reason or ""))
    for r in s.scalars(select(m.CompOffRequest).where(m.CompOffRequest.status == "APPROVED",
                                                      m.CompOffRequest.date.between(look_from, last))):
        absences.append(t.Absence(r.employee_id, r.date, r.date, t.AbsenceKind.COMP_OFF))

    holidays: dict[int, dict[date, str]] = {}
    for h in s.scalars(select(m.PublicHoliday).where(m.PublicHoliday.date.between(look_from, last))):
        holidays.setdefault(h.calendar_id, {})[h.date] = h.name
    default_cal = s.scalar(select(m.HolidayCalendar.id).where(m.HolidayCalendar.is_default))

    # Lookback: the previous month's published version (rest rules across the boundary).
    history: list[t.HistoryDay] = []
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_version = s.scalar(select(m.RosterVersion).join(m.RosterPlan)
                            .where(m.RosterPlan.year == prev_y, m.RosterPlan.month == prev_m,
                                   m.RosterVersion.status == "PUBLISHED"))
    if prev_version is not None:
        for en in s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == prev_version.id,
                                                        m.RosterEntry.date >= look_from)):
            history.append(t.HistoryDay(en.employee_id, en.date, en.status == "WORK", en.shift_id))

    settings = t.SolverSettings(deterministic_time=cfg.solver_deterministic_time,
                                wall_time_limit=cfg.solver_wall_time_limit)
    return t.Problem(year, month, emps, shifts, bps, slots, assignments, overrides, absences, holidays,
                     default_cal, history, settings)


def load_roster(s: Session, version_id: int) -> t.Roster:
    entries = [t.RosterEntry(e.employee_id, e.date, t.EntryStatus(e.status), e.shift_id, t.Source(e.source),
                             e.is_locked)
               for e in s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == version_id))]
    duties = [t.RosterDuty(d.employee_id, d.date, d.brand_process_shift_id, d.brand_process_id, d.shift_id,
                           d.assignment_id, t.Role(d.duty_type), t.Source(d.source), d.is_locked)
              for d in s.scalars(select(m.RosterDuty).where(m.RosterDuty.version_id == version_id))]
    return t.Roster(entries, duties)


# ───────────────────────────── persist ─────────────────────────────
def persist_outcome(
    s: Session,
    problem: t.Problem,
    outcome: Outcome,
    kind: str = "GENERATED",
    created_by: str = "system",
    parent_version_id: int | None = None,
    params: dict | None = None,
    max_suggestions: int = 3,
) -> m.RosterVersion:
    """Store an outcome as a new DRAFT version. Caller owns the transaction (commit)."""
    plan = s.scalar(select(m.RosterPlan).where(m.RosterPlan.year == problem.year,
                                               m.RosterPlan.month == problem.month))
    if plan is None:
        plan = m.RosterPlan(year=problem.year, month=problem.month)
        s.add(plan)
        s.flush()
    next_no = (s.scalar(select(func.max(m.RosterVersion.version_no))
                        .where(m.RosterVersion.plan_id == plan.id)) or 0) + 1

    rep = outcome.report
    version = m.RosterVersion(
        plan_id=plan.id, version_no=next_no, parent_version_id=parent_version_id, kind=kind, status="DRAFT",
        validation_status=outcome.status.value,
        coverage_pct=None, params=params,
        solver_stats={"solve_status": outcome.solve.status.value, **outcome.solve.stats},
        created_by=created_by,
    )
    s.add(version)
    s.flush()

    roster = outcome.roster
    if roster is not None:
        entry_rows: dict[tuple[int, date], m.RosterEntry] = {}
        for e in roster.entries:
            row = m.RosterEntry(version_id=version.id, employee_id=e.employee_id, date=e.date,
                                status=e.status.value, shift_id=e.shift_id, source=e.source.value,
                                is_locked=e.is_locked)
            entry_rows[(e.employee_id, e.date)] = row
        s.add_all(entry_rows.values())
        s.flush()
        s.add_all([
            m.RosterDuty(version_id=version.id, entry_id=entry_rows[(d.employee_id, d.date)].id,
                         employee_id=d.employee_id, date=d.date, shift_id=d.shift_id, entry_status="WORK",
                         brand_process_shift_id=d.slot_id, brand_process_id=d.brand_process_id,
                         assignment_id=d.assignment_id, duty_type=d.duty_type.value, source=d.source.value,
                         is_locked=d.is_locked)
            for d in roster.duties
        ])

    if rep is not None:
        from .validation_service import store_report  # local import: avoids a cycle
        store_report(s, version, problem, roster, rep, max_suggestions)

    for lc in outcome.solve.lock_conflicts:
        s.add(m.RosterConflict(version_id=version.id, type="LOCK_CONFLICT", category="SOLVER", severity="HARD",
                               date=lc.date, employee_id=lc.employee_id, message=lc.reason, status="OPEN"))
    if outcome.status == t.ValidationStatus.SOLVER_TIMEOUT:
        s.add(m.RosterConflict(version_id=version.id, type="SOLVER_TIMEOUT", category="SOLVER", severity="HARD",
                               message="The solver reached its time limit before finding any roster. "
                                       "Retry with a larger SOLVER_WALL_TIME_LIMIT or fewer locked rows.",
                               status="OPEN"))

    s.add(m.AuditLog(actor=created_by, entity_type="roster_version", entity_id=version.id, version_id=version.id,
                     action=kind.lower(), after={"version_no": next_no, "validation_status": outcome.status.value,
                                                 "coverage_pct": rep.coverage_pct if rep else None},
                     reason=(params or {}).get("reason")))
    s.flush()
    return version

