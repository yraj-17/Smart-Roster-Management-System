"""Tiny fluent builder for engine test scenarios."""
from __future__ import annotations

from datetime import date, time

from app.scheduling.types import (
    Absence,
    AbsenceKind,
    Assignment,
    BrandProcess,
    CoverageOverride,
    Employee,
    OffPolicy,
    Problem,
    Role,
    Shift,
    Slot,
    SolverSettings,
)

GEN, MOR, EVE, NGT = 1, 2, 3, 4
ALL_DAYS = 0b1111111
MON_SAT = 0b0111111
FAST = SolverSettings(deterministic_time=10.0, wall_time_limit=60.0)


class PB:
    def __init__(self, year: int = 2026, month: int = 12):
        self.year, self.month = year, month
        self.shifts = [
            Shift(GEN, "GEN", time(9), time(18)),
            Shift(MOR, "MOR", time(7), time(15)),
            Shift(EVE, "EVE", time(14), time(22)),
            Shift(NGT, "NGT", time(22), time(6)),
        ]
        self.employees: list[Employee] = []
        self.bps: list[BrandProcess] = []
        self.slots: list[Slot] = []
        self.assignments: list[Assignment] = []
        self.overrides: list[CoverageOverride] = []
        self.absences: list[Absence] = []
        self.holidays: dict[int, dict[date, str]] = {1: {}}
        self.history = []
        self._brands: dict[str, int] = {}

    def employee(self, name: str, pod: int = 1, **kw) -> int:
        eid = len(self.employees) + 1
        policy = kw.pop("policy", OffPolicy())
        self.employees.append(Employee(eid, f"E{eid:03d}", name, pod, policy=policy, **kw))
        return eid

    def bp(self, brand: str, process: str, mask: int = ALL_DAYS, holidays: bool = False,
           calendar: int | None = None) -> int:
        bid = self._brands.setdefault(brand, len(self._brands) + 1)
        bpid = len(self.bps) + 1
        self.bps.append(BrandProcess(bpid, bid, brand, process, mask, holidays, calendar))
        return bpid

    def slot(self, bp: int, shift: int = GEN, min_staff: int = 1) -> int:
        sid = len(self.slots) + 1
        self.slots.append(Slot(sid, bp, shift, min_staff))
        return sid

    def assign(self, emp: int, bp: int, role: Role = Role.PRIMARY, load: int = 100,
               shift: int | None = None, frm: date = date(2026, 1, 1), to: date | None = None) -> int:
        aid = len(self.assignments) + 1
        self.assignments.append(Assignment(aid, emp, bp, role, load, frm, to, shift))
        return aid

    def leave(self, emp: int, start: date, end: date, kind: AbsenceKind = AbsenceKind.LEAVE):
        self.absences.append(Absence(emp, start, end, kind))

    def holiday(self, d: date, name: str = "Holiday", calendar: int = 1):
        self.holidays.setdefault(calendar, {})[d] = name

    def override(self, slot: int, min_staff: int, dow: int | None = None, on: date | None = None):
        self.overrides.append(CoverageOverride(slot, min_staff, dow, on))

    def build(self, settings: SolverSettings = FAST) -> Problem:
        return Problem(self.year, self.month, self.employees, self.shifts, self.bps, self.slots,
                       self.assignments, self.overrides, self.absences, self.holidays, 1,
                       self.history, settings)


def D(day: int) -> date:
    return date(2026, 12, day)
