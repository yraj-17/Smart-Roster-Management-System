"""Calendar expansion and shared lookups.

Two independent concerns live here, deliberately kept apart:

* **Brand-process operating calendar** - does a process operate on a date, and how
  many people does each of its shifts need?  Uses the *brand's* holiday calendar.
* **Employee availability / rest** - is an employee absent, is it their public
  holiday, is it a fixed off day?  Uses the *employee's* holiday calendar.

They only meet when candidate duties are generated (an assignment of an available
employee to a required slot).  Solver, validator and suggestion ranker all read
requirements from :class:`Context` so they can never disagree.
"""
from __future__ import annotations

import calendar as _cal
from collections import defaultdict
from datetime import date, timedelta
from functools import cached_property

from .types import (
    AbsenceKind,
    Assignment,
    BrandProcess,
    Employee,
    Problem,
    Role,
    Shift,
    Slot,
)

ABSENCE_PRIORITY = [AbsenceKind.LEAVE, AbsenceKind.COMP_OFF, AbsenceKind.UNAVAILABLE]


def month_days(year: int, month: int) -> list[date]:
    n = _cal.monthrange(year, month)[1]
    return [date(year, month, i) for i in range(1, n + 1)]


def week_start(d: date) -> date:
    """Weeks run Monday-Sunday."""
    return d - timedelta(days=d.weekday())


class Context:
    """Pre-computed indexes over a :class:`Problem`."""

    def __init__(self, problem: Problem):
        self.p = problem
        self.days = month_days(problem.year, problem.month)
        self.first_day, self.last_day = self.days[0], self.days[-1]

        self.employees = {e.id: e for e in problem.employees if e.active}
        self.shifts: dict[int, Shift] = {s.id: s for s in problem.shifts}
        self.bps: dict[int, BrandProcess] = {b.id: b for b in problem.brand_processes}
        self.slots: dict[int, Slot] = {s.id: s for s in problem.slots}
        self.assignments: dict[int, Assignment] = {a.id: a for a in problem.assignments}

        self.slots_by_bp: dict[int, list[Slot]] = defaultdict(list)
        for s in problem.slots:
            self.slots_by_bp[s.brand_process_id].append(s)

        self.assignments_by_bp: dict[int, list[Assignment]] = defaultdict(list)
        self.assignments_by_emp: dict[int, list[Assignment]] = defaultdict(list)
        for a in problem.assignments:
            self.assignments_by_bp[a.brand_process_id].append(a)
            self.assignments_by_emp[a.employee_id].append(a)

        self._override_date: dict[tuple[int, date], int] = {}
        self._override_dow: dict[tuple[int, int], int] = {}
        for o in problem.overrides:
            if o.specific_date is not None:
                self._override_date[(o.slot_id, o.specific_date)] = o.min_staff
            elif o.day_of_week is not None:
                self._override_dow[(o.slot_id, o.day_of_week)] = o.min_staff

        self._absence: dict[tuple[int, date], AbsenceKind] = {}
        for ab in sorted(problem.absences, key=lambda a: ABSENCE_PRIORITY.index(a.kind), reverse=True):
            d = ab.start
            while d <= ab.end:
                self._absence[(ab.employee_id, d)] = ab.kind  # highest priority written last
                d += timedelta(days=1)

        self.history = {(h.employee_id, h.date): h for h in problem.history}

    # ── holidays ──────────────────────────────────────────────────────────────
    def holiday_name(self, calendar_id: int | None, d: date) -> str | None:
        cal = calendar_id if calendar_id is not None else self.p.default_calendar_id
        if cal is None:
            return None
        return self.p.holidays.get(cal, {}).get(d)

    # ── brand-process operating calendar ─────────────────────────────────────
    def bp_operates(self, bp: BrandProcess, d: date) -> bool:
        if not bp.active or not (bp.operating_days_mask >> d.weekday()) & 1:
            return False
        if not bp.operates_on_holidays and self.holiday_name(bp.holiday_calendar_id, d):
            return False
        return True

    def required(self, slot_id: int, d: date) -> int:
        """Resolved minimum headcount for a slot on a date (0 = not required).

        Precedence: not operating -> 0; specific-date override; weekday override;
        the shift's default minimum.
        """
        slot = self.slots.get(slot_id)
        if slot is None or not slot.active:
            return 0
        bp = self.bps.get(slot.brand_process_id)
        if bp is None or not self.bp_operates(bp, d):
            return 0
        if (slot_id, d) in self._override_date:
            return self._override_date[(slot_id, d)]
        if (slot_id, d.weekday()) in self._override_dow:
            return self._override_dow[(slot_id, d.weekday())]
        return slot.default_min_staff

    @cached_property
    def requirements(self) -> dict[tuple[int, date], int]:
        """All (slot, day) pairs with required > 0 in the month."""
        out = {}
        for s in self.p.slots:
            for d in self.days:
                r = self.required(s.id, d)
                if r > 0:
                    out[(s.id, d)] = r
        return out

    # ── employee availability ────────────────────────────────────────────────
    def absence(self, employee_id: int, d: date) -> AbsenceKind | None:
        return self._absence.get((employee_id, d))

    def employee_holiday(self, emp: Employee, d: date) -> str | None:
        return self.holiday_name(emp.holiday_calendar_id, d)

    def is_fixed_off(self, emp: Employee, d: date) -> bool:
        return d.weekday() in emp.fixed_off_days

    def preferred_off_priority(self, emp: Employee, d: date) -> int:
        for dow, prio in emp.preferred_off_days:
            if dow == d.weekday():
                return prio
        return 0

    def can_work(self, emp: Employee, d: date) -> bool:
        """Hard availability: not absent and not a fixed off day."""
        return self.absence(emp.id, d) is None and not self.is_fixed_off(emp, d)

    # ── eligibility ──────────────────────────────────────────────────────────
    def assignment_for(self, employee_id: int, bp_id: int, d: date) -> Assignment | None:
        """The unique effective assignment (DB exclusion constraint guarantees <=1)."""
        for a in self.assignments_by_emp.get(employee_id, ()):
            if a.brand_process_id == bp_id and a.effective_on(d):
                return a
        return None

    def eligible(self, a: Assignment, slot: Slot, d: date) -> bool:
        emp = self.employees.get(a.employee_id)
        bp = self.bps.get(a.brand_process_id)
        return (
            emp is not None
            and bp is not None
            and bp.active
            and slot.active
            and slot.brand_process_id == a.brand_process_id
            and a.effective_on(d)
            and (a.shift_id is None or a.shift_id == slot.shift_id)
        )

    def eligible_assignments(self, slot: Slot, d: date, role: Role | None = None) -> list[Assignment]:
        return [
            a
            for a in self.assignments_by_bp.get(slot.brand_process_id, ())
            if (role is None or a.role == role) and self.eligible(a, slot, d)
        ]

    # ── rest helpers ─────────────────────────────────────────────────────────
    def rest_gap_ok(self, emp: Employee, shift_a: int, shift_b: int) -> bool:
        """Can `emp` work shift_a on day D and shift_b on day D+1?"""
        a, b = self.shifts[shift_a], self.shifts[shift_b]
        gap_minutes = (1440 + b.start_min) - a.end_min
        return gap_minutes >= emp.policy.min_rest_hours * 60

    def weeks(self) -> list[list[date]]:
        """Monday-Sunday weeks intersecting the month (only in-month days listed)."""
        out: dict[date, list[date]] = defaultdict(list)
        for d in self.days:
            out[week_start(d)].append(d)
        return [out[k] for k in sorted(out)]

    def required_offs_in_week(self, emp: Employee, week: list[date]) -> int:
        """Offs the employee must take on the in-month days of `week`.

        Days of the week before the month use published history when available;
        unknown days (no history, or after month end) are assumed free to be offs,
        so partial weeks never over-constrain.  The next month's generation sees
        this month as history and enforces the full week.
        """
        ws = week_start(week[0])
        known_offs = unknown = 0
        for i in range(7):
            d = ws + timedelta(days=i)
            if self.first_day <= d <= self.last_day:
                continue
            h = self.history.get((emp.id, d))
            if h is None:
                unknown += 1
            elif not h.working and (
                emp.policy.holidays_count_as_rest or not self.employee_holiday(emp, d)
            ):
                known_offs += 1
        return max(0, emp.policy.min_offs_per_week - known_offs - unknown)

    def history_streak_before_month(self, emp: Employee) -> int:
        """Consecutive worked days immediately before the month (from history)."""
        streak, d = 0, self.first_day - timedelta(days=1)
        while (h := self.history.get((emp.id, d))) is not None and h.working:
            streak += 1
            d -= timedelta(days=1)
        return streak

    def history_shift_before_month(self, emp: Employee) -> int | None:
        h = self.history.get((emp.id, self.first_day - timedelta(days=1)))
        return h.shift_id if h and h.working else None
