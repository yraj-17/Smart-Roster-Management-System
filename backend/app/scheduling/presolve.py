"""Pre-solve diagnostics.

Run before the solver to (a) prove which coverage gaps are *unavoidable* - fewer
eligible, available people exist than the slot requires - and (b) surface
master-data problems (over-allocation, incompatible primary shifts, slots with
nobody assigned).  The results feed conflict explanations; they never change
what the solver is allowed to do.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .calendar import Context
from .types import Category, Role, Severity


@dataclass(frozen=True)
class Issue:
    type: str
    category: Category
    severity: Severity
    message: str
    date: date | None = None
    employee_id: int | None = None
    slot_id: int | None = None
    details: dict = field(default_factory=dict, hash=False, compare=False)


@dataclass
class PresolveReport:
    # (slot_id, date) -> number of eligible people available (primary + backup)
    capacity: dict[tuple[int, date], int] = field(default_factory=dict)
    unavoidable: set[tuple[int, date]] = field(default_factory=set)
    issues: list[Issue] = field(default_factory=list)


def unavailability_reason(ctx: Context, employee_id: int, d: date) -> str | None:
    emp = ctx.employees.get(employee_id)
    if emp is None:
        return "inactive"
    ab = ctx.absence(employee_id, d)
    if ab is not None:
        return {"LEAVE": "on approved leave", "COMP_OFF": "on comp-off",
                "UNAVAILABLE": "marked unavailable"}[ab.value]
    if ctx.is_fixed_off(emp, d):
        return "fixed weekly off"
    return None


def presolve(ctx: Context) -> PresolveReport:
    rep = PresolveReport()

    # Coverage capacity per required slot-day.
    for (slot_id, d), req in ctx.requirements.items():
        slot = ctx.slots[slot_id]
        eligible = ctx.eligible_assignments(slot, d)
        available = [a for a in eligible if ctx.can_work(ctx.employees[a.employee_id], d)]
        rep.capacity[(slot_id, d)] = len(available)
        if len(available) < req:
            rep.unavoidable.add((slot_id, d))

    # Slots that are required but have no assignment at all in the month.
    for slot in ctx.p.slots:
        req_days = [d for d in ctx.days if (slot.id, d) in ctx.requirements]
        if req_days and not any(ctx.eligible_assignments(slot, d) for d in req_days):
            bp = ctx.bps[slot.brand_process_id]
            rep.issues.append(Issue(
                "NO_ASSIGNED_STAFF", Category.CONFIG, Severity.SOFT,
                f"{bp.label} {ctx.shifts[slot.shift_id].code} requires coverage on "
                f"{len(req_days)} day(s) but no employee is assigned to it.",
                slot_id=slot.id,
            ))

    # Per employee: over-allocation and incompatible primary shifts.
    for emp in ctx.employees.values():
        over_days: list[date] = []
        incompatible_days: list[date] = []
        worst_load = 0
        shift_sets: set[tuple[int, ...]] = set()
        for d in ctx.days:
            load_by_shift: dict[int, int] = defaultdict(int)
            for a in ctx.assignments_by_emp.get(emp.id, ()):
                if a.role != Role.PRIMARY or not a.effective_on(d):
                    continue
                for slot in ctx.slots_by_bp.get(a.brand_process_id, ()):
                    if (slot.id, d) in ctx.requirements and ctx.eligible(a, slot, d):
                        load_by_shift[slot.shift_id] += a.load_pct
            if not load_by_shift:
                continue
            # Primary duties restricted to a single shift that exceed the cap.
            peak = max(load_by_shift.values())
            if peak > emp.max_daily_load_pct:
                over_days.append(d)
                worst_load = max(worst_load, peak)
            # Primaries that can only be done on different shifts on the same day.
            if _needs_multiple_shifts(ctx, emp.id, d):
                incompatible_days.append(d)
                shift_sets.add(tuple(sorted(load_by_shift)))
        if over_days:
            rep.issues.append(Issue(
                "OVER_ALLOCATED", Category.CONFIG, Severity.SOFT,
                f"{emp.name}'s primary assignments need up to {worst_load}% load on one shift "
                f"(cap {emp.max_daily_load_pct}%) on {len(over_days)} day(s); some primary "
                f"duties cannot be scheduled.",
                employee_id=emp.id, details={"days": [d.isoformat() for d in over_days]},
            ))
        if incompatible_days:
            codes = sorted({ctx.shifts[s].code for t in shift_sets for s in t})
            rep.issues.append(Issue(
                "INCOMPATIBLE_PRIMARY_SHIFTS", Category.CONFIG, Severity.SOFT,
                f"{emp.name} holds primary assignments that can only be worked on different "
                f"shifts ({', '.join(codes)}) on {len(incompatible_days)} day(s). An employee works "
                f"one shift per day, so one of them will need cover.",
                employee_id=emp.id, details={"days": [d.isoformat() for d in incompatible_days]},
            ))
    return rep


def _needs_multiple_shifts(ctx: Context, employee_id: int, d: date) -> bool:
    """True if no single shift lets the employee perform every required primary bp."""
    required_bps: dict[int, set[int]] = {}
    for a in ctx.assignments_by_emp.get(employee_id, ()):
        if a.role != Role.PRIMARY or not a.effective_on(d):
            continue
        shifts = {
            s.shift_id for s in ctx.slots_by_bp.get(a.brand_process_id, ())
            if (s.id, d) in ctx.requirements and ctx.eligible(a, s, d)
        }
        if shifts:
            required_bps[a.brand_process_id] = shifts
    if len(required_bps) < 2:
        return False
    common = set.intersection(*required_bps.values())
    return not common
