"""Plain data structures for the scheduling engine.

The engine never imports SQLAlchemy or FastAPI. Everything it needs arrives as
these immutable dataclasses, and everything it produces leaves as dataclasses.
That keeps the scheduling logic unit-testable without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum


# ───────────────────────── enums (string values match DB CHECK constraints) ──
class Role(str, Enum):
    PRIMARY = "PRIMARY"
    BACKUP = "BACKUP"


class EntryStatus(str, Enum):
    WORK = "WORK"
    WEEKLY_OFF = "WEEKLY_OFF"
    LEAVE = "LEAVE"
    COMP_OFF = "COMP_OFF"
    HOLIDAY = "HOLIDAY"
    UNAVAILABLE = "UNAVAILABLE"


class AbsenceKind(str, Enum):
    LEAVE = "LEAVE"
    COMP_OFF = "COMP_OFF"
    UNAVAILABLE = "UNAVAILABLE"


class Source(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    REOPT = "REOPT"


class SlotStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    MET = "MET"
    UNDERSTAFFED = "UNDERSTAFFED"
    UNCOVERED = "UNCOVERED"


# Precedence for roll-ups: higher = worse.
SLOT_STATUS_RANK = {
    SlotStatus.NOT_REQUIRED: 0,
    SlotStatus.MET: 1,
    SlotStatus.UNDERSTAFFED: 2,
    SlotStatus.UNCOVERED: 3,
}


class SolveStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"          # proven: no assignment satisfies hard rules
    SOLVER_TIMEOUT = "SOLVER_TIMEOUT"  # limit hit before any solution was found
    MODEL_INVALID = "MODEL_INVALID"


class ValidationStatus(str, Enum):
    FULLY_COVERED = "FULLY_COVERED"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    INVALID = "INVALID"
    INFEASIBLE = "INFEASIBLE"
    SOLVER_TIMEOUT = "SOLVER_TIMEOUT"
    STALE = "STALE"


class Severity(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class Category(str, Enum):
    INTEGRITY = "INTEGRITY"          # structurally broken records      -> INVALID
    EMPLOYEE_RULE = "EMPLOYEE_RULE"  # mandatory employee rules broken  -> INVALID
    COVERAGE = "COVERAGE"            # mandatory coverage missing       -> PARTIALLY_COVERED
    PREFERENCE = "PREFERENCE"        # soft preferences                 -> warning only
    CONFIG = "CONFIG"                # master-data problems             -> warning only
    SOLVER = "SOLVER"                # infeasible / timeout explanation


# ───────────────────────── master data ──
@dataclass(frozen=True)
class Shift:
    id: int
    code: str
    start: time
    end: time

    @property
    def start_min(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_min(self) -> int:
        """End in minutes from the start of the shift's own day (may exceed 1440)."""
        end = self.end.hour * 60 + self.end.minute
        return end + 1440 if end <= self.start_min else end


@dataclass(frozen=True)
class OffPolicy:
    min_offs_per_week: int = 1
    max_consecutive_work_days: int = 6
    min_rest_hours: int = 11
    holidays_count_as_rest: bool = True


@dataclass(frozen=True)
class Employee:
    id: int
    code: str
    name: str
    pod_id: int
    policy: OffPolicy = OffPolicy()
    holiday_calendar_id: int | None = None
    max_daily_load_pct: int = 100
    backup_stretch_pct: int = 25
    fixed_off_days: frozenset[int] = frozenset()          # 0 = Monday (hard)
    preferred_off_days: tuple[tuple[int, int], ...] = ()  # (day_of_week, priority) (soft)
    active: bool = True


@dataclass(frozen=True)
class BrandProcess:
    id: int
    brand_id: int
    brand_name: str
    process_code: str
    operating_days_mask: int = 0b1111111   # bit0 = Monday
    operates_on_holidays: bool = False
    holiday_calendar_id: int | None = None  # the brand's calendar; None = default
    active: bool = True

    @property
    def label(self) -> str:
        return f"{self.brand_name}/{self.process_code}"


@dataclass(frozen=True)
class Slot:
    """A brand_process_shift: the unit of coverage (combined with a date)."""
    id: int
    brand_process_id: int
    shift_id: int
    default_min_staff: int = 1
    active: bool = True


@dataclass(frozen=True)
class CoverageOverride:
    slot_id: int
    min_staff: int
    day_of_week: int | None = None
    specific_date: date | None = None


@dataclass(frozen=True)
class Assignment:
    id: int
    employee_id: int
    brand_process_id: int
    role: Role
    load_pct: int
    effective_from: date
    effective_to: date | None = None
    shift_id: int | None = None  # None = any shift the process runs

    def effective_on(self, d: date) -> bool:
        return self.effective_from <= d and (self.effective_to is None or d <= self.effective_to)


@dataclass(frozen=True)
class Absence:
    employee_id: int
    start: date
    end: date
    kind: AbsenceKind
    note: str = ""


@dataclass(frozen=True)
class HistoryDay:
    """A day from the previous (published) month, used for rest-rule lookback."""
    employee_id: int
    date: date
    working: bool
    shift_id: int | None = None


# ───────────────────────── roster rows ──
@dataclass(frozen=True)
class RosterEntry:
    employee_id: int
    date: date
    status: EntryStatus
    shift_id: int | None = None
    source: Source = Source.AUTO
    is_locked: bool = False


@dataclass(frozen=True)
class RosterDuty:
    employee_id: int
    date: date
    slot_id: int
    brand_process_id: int
    shift_id: int
    assignment_id: int
    duty_type: Role
    source: Source = Source.AUTO
    is_locked: bool = False


@dataclass
class Roster:
    entries: list[RosterEntry] = field(default_factory=list)
    duties: list[RosterDuty] = field(default_factory=list)

    def entry_map(self) -> dict[tuple[int, date], RosterEntry]:
        return {(e.employee_id, e.date): e for e in self.entries}

    def duties_by_day(self) -> dict[tuple[int, date], list[RosterDuty]]:
        out: dict[tuple[int, date], list[RosterDuty]] = {}
        for d in self.duties:
            out.setdefault((d.employee_id, d.date), []).append(d)
        return out


@dataclass(frozen=True)
class Weights:
    shortfall: int = 100_000
    excess_off: int = 2_000
    primary_continuity: int = 1_000
    backup_activation: int = 300
    holiday_work: int = 200
    preferred_off: int = 50        # multiplied by preference priority
    weekend_fairness: int = 20
    stability: int = 60


@dataclass(frozen=True)
class SolverSettings:
    seed: int = 42
    deterministic_time: float = 30.0   # CP-SAT deterministic-time budget (reproducible)
    wall_time_limit: float = 60.0      # safety net; hitting it may produce SOLVER_TIMEOUT
    weekend_off_target: int = 2        # desired weekend days off per employee per month
    weights: Weights = Weights()


@dataclass
class Problem:
    """Everything the engine needs to plan one month."""
    year: int
    month: int
    employees: list[Employee]
    shifts: list[Shift]
    brand_processes: list[BrandProcess]
    slots: list[Slot]
    assignments: list[Assignment]
    overrides: list[CoverageOverride] = field(default_factory=list)
    absences: list[Absence] = field(default_factory=list)
    # calendar_id -> {date: holiday name}
    holidays: dict[int, dict[date, str]] = field(default_factory=dict)
    default_calendar_id: int | None = None
    history: list[HistoryDay] = field(default_factory=list)
    settings: SolverSettings = SolverSettings()
