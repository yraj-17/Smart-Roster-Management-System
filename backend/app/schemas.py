"""Request/response models. Inputs are validated here before any service runs."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Code = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_\-]+$")
Name80 = Field(min_length=1, max_length=80)
Name120 = Field(min_length=1, max_length=120)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────────────────────── organisation ─────────────────────────────
class WeeklyOffPolicyIn(BaseModel):
    name: str = Name80
    min_offs_per_week: int = Field(1, ge=0, le=7)
    max_consecutive_work_days: int = Field(6, ge=1, le=14)
    min_rest_hours: int = Field(11, ge=0, le=24)
    holidays_count_as_rest: bool = True


class WeeklyOffPolicyOut(WeeklyOffPolicyIn, Out):
    id: int


class PodIn(BaseModel):
    name: str = Name80
    lead_employee_id: int | None = None
    active: bool = True


class PodOut(PodIn, Out):
    id: int


class OffDayIn(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0 = Monday")
    kind: Literal["FIXED", "PREFERRED"]
    priority: int = Field(1, ge=1, le=5)


class OffDayOut(OffDayIn, Out):
    id: int


class EmployeeIn(BaseModel):
    code: str = Code
    name: str = Name120
    email: str = Field(max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    pod_id: int
    weekly_off_policy_id: int
    holiday_calendar_id: int | None = None
    max_daily_load_pct: int = Field(100, ge=1, le=200)
    backup_stretch_pct: int = Field(25, ge=0, le=100)
    active: bool = True
    off_days: list[OffDayIn] = []

    @model_validator(mode="after")
    def _unique_days(self):
        days = [o.day_of_week for o in self.off_days]
        if len(days) != len(set(days)):
            raise ValueError("each day of week may appear only once in off_days")
        return self


class EmployeeOut(Out):
    id: int
    code: str
    name: str
    email: str
    pod_id: int
    weekly_off_policy_id: int
    holiday_calendar_id: int | None
    max_daily_load_pct: int
    backup_stretch_pct: int
    active: bool
    off_days: list[OffDayOut]


# ───────────────────────────── catalog ─────────────────────────────
class ProcessIn(BaseModel):
    code: str = Code
    name: str = Name80
    description: str | None = None
    active: bool = True


class ProcessOut(ProcessIn, Out):
    id: int


class BrandIn(BaseModel):
    code: str = Code
    name: str = Name120
    holiday_calendar_id: int | None = None
    notes: str | None = None
    active: bool = True


class BrandOut(BrandIn, Out):
    id: int


class ShiftIn(BaseModel):
    code: str = Code
    name: str = Field(min_length=1, max_length=60)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _non_zero(self):
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time must differ")
        return self


class ShiftOut(ShiftIn, Out):
    id: int


class BrandProcessIn(BaseModel):
    brand_id: int
    process_id: int
    operating_days_mask: int = Field(127, ge=0, le=127, description="bit0 = Monday ... bit6 = Sunday")
    operates_on_holidays: bool = False
    active: bool = True


class BrandProcessOut(BrandProcessIn, Out):
    id: int


class SlotIn(BaseModel):
    brand_process_id: int
    shift_id: int
    default_min_staff: int = Field(1, ge=0, le=50)
    active: bool = True


class SlotOut(SlotIn, Out):
    id: int


class CoverageRequirementIn(BaseModel):
    brand_process_shift_id: int
    day_of_week: int | None = Field(None, ge=0, le=6)
    specific_date: date | None = None
    min_staff: int = Field(ge=0, le=50)
    reason: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.day_of_week is None) == (self.specific_date is None):
            raise ValueError("set exactly one of day_of_week or specific_date")
        return self


class CoverageRequirementOut(CoverageRequirementIn, Out):
    id: int


class AssignmentIn(BaseModel):
    employee_id: int
    brand_process_id: int
    shift_id: int | None = None
    role: Literal["PRIMARY", "BACKUP"]
    load_pct: int = Field(ge=1, le=100)
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class AssignmentOut(AssignmentIn, Out):
    id: int


# ───────────────────────────── holidays ─────────────────────────────
class HolidayCalendarIn(BaseModel):
    name: str = Name80
    region: str | None = Field(None, max_length=80)
    is_default: bool = False


class HolidayCalendarOut(HolidayCalendarIn, Out):
    id: int


class HolidayIn(BaseModel):
    date: date
    name: str = Name120
    kind: Literal["NATIONAL", "REGIONAL", "OPTIONAL"] = "NATIONAL"


class HolidayOut(HolidayIn, Out):
    id: int
    calendar_id: int


# ───────────────────────────── availability ─────────────────────────────
class LeaveIn(BaseModel):
    employee_id: int
    start_date: date
    end_date: date
    leave_type: Literal["PLANNED", "SICK", "CASUAL", "OTHER"] = "PLANNED"
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > 90:
            raise ValueError("a single leave may not exceed 90 days")
        return self


class LeaveOut(Out):
    id: int
    employee_id: int
    start_date: date
    end_date: date
    leave_type: str
    status: str
    reason: str | None
    decided_by: str | None
    decided_at: datetime | None


class UnavailabilityIn(BaseModel):
    employee_id: int
    start_date: date
    end_date: date
    reason: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class UnavailabilityOut(UnavailabilityIn, Out):
    id: int


class CompOffGrantIn(BaseModel):
    employee_id: int
    earned_on: date
    note: str | None = Field(None, max_length=500)


class CompOffCreditOut(Out):
    id: int
    employee_id: int
    earned_on: date
    source: str
    source_version_id: int | None
    status: str
    expires_on: date | None
    consumed_on: date | None
    note: str | None


class CompOffRequestIn(BaseModel):
    employee_id: int
    date: date
    credit_id: int


class CompOffRequestOut(Out):
    id: int
    employee_id: int
    date: date
    credit_id: int
    status: str
    decided_by: str | None


class DecisionIn(BaseModel):
    reason: str | None = Field(None, max_length=500)


# ───────────────────────────── rosters ─────────────────────────────
class GenerateIn(BaseModel):
    notes: str | None = Field(None, max_length=500)


class VersionOut(Out):
    id: int
    plan_id: int
    version_no: int
    parent_version_id: int | None
    kind: str
    status: str
    validation_status: str
    coverage_pct: float | None
    summary: dict | None
    solver_stats: dict | None
    params: dict | None
    notes: str | None
    created_by: str | None
    created_at: datetime
    published_by: str | None
    published_at: datetime | None
    year: int | None = None
    month: int | None = None


class DayEditIn(BaseModel):
    """Replace one employee-day: its status, shift and complete duty set."""
    status: Literal["WORK", "WEEKLY_OFF", "LEAVE", "COMP_OFF", "HOLIDAY", "UNAVAILABLE"]
    shift_id: int | None = None
    slot_ids: list[int] = Field(default_factory=list, description="brand_process_shift ids")
    note: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "WORK":
            if self.shift_id is None or not self.slot_ids:
                raise ValueError("a WORK day needs a shift_id and at least one slot")
        elif self.shift_id is not None or self.slot_ids:
            raise ValueError("only WORK days may have a shift or duties")
        if len(self.slot_ids) != len(set(self.slot_ids)):
            raise ValueError("duplicate slot ids")
        return self


class DutyIn(BaseModel):
    employee_id: int
    date: date
    brand_process_shift_id: int


class ReoptimizeIn(BaseModel):
    date_from: date
    date_to: date
    employee_ids: list[int] | None = Field(
        None, description="employees whose change triggered this; scope = them + everyone on their brand-processes")
    whole_window: bool = Field(False, description="free every employee inside the window")
    override_manual_entry_ids: list[int] = Field(default_factory=list,
                                                 description="manual rows the manager allows the solver to change")
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _window(self):
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        if self.date_from.replace(day=1) != self.date_to.replace(day=1):
            raise ValueError("the window must lie within one month")
        return self


class AcknowledgeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class ApplySuggestionIn(BaseModel):
    employee_id: int
    action: Literal["ADD_DUTY", "WORK_ON_OFF_DAY", "CHANGE_SHIFT"]


class ImpactIn(BaseModel):
    employee_id: int
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def _window(self):
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        return self


class ConflictOut(Out):
    id: int
    version_id: int
    type: str
    category: str
    severity: str
    date: date | None
    employee_id: int | None
    brand_process_shift_id: int | None
    message: str
    explanation: dict | None
    suggestions: list | None
    status: str
    ack_reason: str | None
    ack_by: str | None
    ack_at: datetime | None


class AuditOut(Out):
    id: int
    actor: str
    entity_type: str
    entity_id: int | None
    version_id: int | None
    action: str
    before: dict | None
    after: dict | None
    reason: str | None
    created_at: datetime
