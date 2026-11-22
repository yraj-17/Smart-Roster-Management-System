"""Independent roster validator.

Re-derives every rule from master data and the roster rows; it never trusts the
solver.  The same function validates freshly generated rosters, manually edited
rosters and rosters whose inputs changed (new leave, edited holiday, ...).

Classification
--------------
INVALID            any INTEGRITY or EMPLOYEE_RULE issue
PARTIALLY_COVERED  rules intact but >=1 required slot UNDERSTAFFED / UNCOVERED
FULLY_COVERED      every required slot MET and zero hard violations

Only *valid* duties count toward coverage (a duty on a leave day, on a non-WORK
entry, with the wrong shift or without a valid assignment counts as 0), and an
employee counts at most once per slot (COUNT DISTINCT employee).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .calendar import Context, week_start
from .presolve import Issue, presolve
from .types import (
    SLOT_STATUS_RANK,
    Category,
    EntryStatus,
    Problem,
    Role,
    Roster,
    RosterDuty,
    Severity,
    SlotStatus,
    SolveStatus,
    ValidationStatus,
)


@dataclass(frozen=True)
class SlotCoverage:
    slot_id: int
    brand_process_id: int
    shift_id: int
    date: date
    required: int
    staffed: int
    primary_count: int
    backup_count: int
    backup_capacity: int  # eligible backups not activated (information only)
    status: SlotStatus


@dataclass
class ValidationReport:
    status: ValidationStatus
    coverage: list[SlotCoverage] = field(default_factory=list)
    process_day: dict[tuple[int, date], SlotStatus] = field(default_factory=dict)
    brand_day: dict[tuple[int, date], SlotStatus] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    coverage_pct: float = 100.0

    def issues_of(self, *types: str) -> list[Issue]:
        return [i for i in self.issues if i.type in types]

    @property
    def hard_rule_violations(self) -> int:
        return sum(i.category in (Category.INTEGRITY, Category.EMPLOYEE_RULE) for i in self.issues)

    @property
    def gaps(self) -> list[SlotCoverage]:
        return [c for c in self.coverage if c.status in (SlotStatus.UNDERSTAFFED, SlotStatus.UNCOVERED)]


def slot_status(required: int, staffed: int) -> SlotStatus:
    if required <= 0:
        return SlotStatus.NOT_REQUIRED
    if staffed >= required:
        return SlotStatus.MET
    return SlotStatus.UNDERSTAFFED if staffed > 0 else SlotStatus.UNCOVERED


def worst(statuses) -> SlotStatus:
    """Roll-up precedence: UNCOVERED > UNDERSTAFFED > MET > NOT_REQUIRED."""
    return max(statuses, key=SLOT_STATUS_RANK.__getitem__, default=SlotStatus.NOT_REQUIRED)


def validate(problem: Problem, roster: Roster) -> ValidationReport:
    ctx = Context(problem)
    issues: list[Issue] = []
    names = {e.id: e.name for e in problem.employees}
    fmt = lambda d: d.strftime("%d %b")  # noqa: E731

    def add(type_, cat, sev, msg, d=None, emp=None, slot=None, **details):
        issues.append(Issue(type_, cat, sev, msg, d, emp, slot, details))

    # ── 1. entries ──────────────────────────────────────────────────────────
    entries: dict[tuple[int, date], object] = {}
    for en in roster.entries:
        key = (en.employee_id, en.date)
        if key in entries:
            add("DUPLICATE_ENTRY", Category.INTEGRITY, Severity.HARD,
                f"Duplicate roster entry for {names.get(en.employee_id)} on {fmt(en.date)}.",
                en.date, en.employee_id)
            continue
        entries[key] = en
        if en.employee_id not in ctx.employees:
            add("ENTRY_FOR_INACTIVE_EMPLOYEE", Category.INTEGRITY, Severity.HARD,
                f"Roster entry for inactive/unknown employee #{en.employee_id}.", en.date, en.employee_id)
        if (en.status == EntryStatus.WORK) != (en.shift_id is not None):
            add("ENTRY_SHIFT_MISMATCH", Category.INTEGRITY, Severity.HARD,
                f"{names.get(en.employee_id)} on {fmt(en.date)}: a shift must be set if and only "
                f"if the status is WORK.", en.date, en.employee_id)
    for emp in ctx.employees.values():
        for d in ctx.days:
            if (emp.id, d) not in entries:
                add("MISSING_ENTRY", Category.INTEGRITY, Severity.HARD,
                    f"No roster entry for {emp.name} on {fmt(d)}.", d, emp.id)

    # ── 2. duties: integrity + eligibility ──────────────────────────────────
    invalid: set[int] = set()           # indexes into roster.duties
    seen_bp: set[tuple[int, date, int]] = set()
    for i, du in enumerate(roster.duties):
        who, when = names.get(du.employee_id, f"#{du.employee_id}"), fmt(du.date)
        en = entries.get((du.employee_id, du.date))
        if en is None or en.status != EntryStatus.WORK:
            add("DUTY_ON_NON_WORK_DAY", Category.INTEGRITY, Severity.HARD,
                f"{who} has a duty on {when} but the day is "
                f"{'missing' if en is None else en.status.value}.", du.date, du.employee_id, du.slot_id)
            invalid.add(i)
        elif en.shift_id != du.shift_id:
            add("DUTY_SHIFT_MISMATCH", Category.INTEGRITY, Severity.HARD,
                f"{who} on {when}: duty shift differs from the day's shift.",
                du.date, du.employee_id, du.slot_id)
            invalid.add(i)
        slot = ctx.slots.get(du.slot_id)
        if slot is None or slot.shift_id != du.shift_id or slot.brand_process_id != du.brand_process_id:
            add("DUTY_SLOT_MISMATCH", Category.INTEGRITY, Severity.HARD,
                f"{who} on {when}: duty does not match its brand-process shift.",
                du.date, du.employee_id, du.slot_id)
            invalid.add(i)
        a = ctx.assignments.get(du.assignment_id)
        reason = None
        if a is None:
            reason = "assignment does not exist"
        elif a.employee_id != du.employee_id or a.brand_process_id != du.brand_process_id:
            reason = "assignment belongs to another employee or brand-process"
        elif a.role != du.duty_type:
            reason = f"duty type {du.duty_type.value} differs from assignment role {a.role.value}"
        elif not a.effective_on(du.date):
            reason = "assignment is not effective on this date"
        elif a.shift_id is not None and a.shift_id != du.shift_id:
            reason = "assignment does not allow this shift"
        elif slot is not None and not ctx.eligible(a, slot, du.date):
            reason = "employee, brand-process or shift is inactive"
        if reason:
            add("INELIGIBLE_DUTY", Category.INTEGRITY, Severity.HARD,
                f"{who} on {when}: {reason}.", du.date, du.employee_id, du.slot_id)
            invalid.add(i)
        k = (du.employee_id, du.date, du.brand_process_id)
        if k in seen_bp:
            add("DUPLICATE_DUTY", Category.INTEGRITY, Severity.HARD,
                f"{who} has two duties for the same brand-process on {when}.",
                du.date, du.employee_id, du.slot_id)
            invalid.add(i)
        seen_bp.add(k)

    duties_by_day: dict[tuple[int, date], list[tuple[int, RosterDuty]]] = defaultdict(list)
    for i, du in enumerate(roster.duties):
        duties_by_day[(du.employee_id, du.date)].append((i, du))

    # ── 3. per employee-day: duty presence, load, absence, fixed offs ───────
    for (e, d), en in entries.items():
        emp = ctx.employees.get(e)
        if emp is None or en.status != EntryStatus.WORK:
            continue
        day = duties_by_day.get((e, d), [])
        if not day:
            add("WORK_WITHOUT_DUTY", Category.INTEGRITY, Severity.HARD,
                f"{emp.name} is rostered to work on {fmt(d)} but has no duties.", d, e)
        prim = total = 0
        for _i, du in day:
            a = ctx.assignments.get(du.assignment_id)
            load = a.load_pct if a else 0
            total += load
            prim += load if du.duty_type == Role.PRIMARY else 0
        if prim > emp.max_daily_load_pct or total > emp.max_daily_load_pct + emp.backup_stretch_pct:
            add("LOAD_CAP_EXCEEDED", Category.EMPLOYEE_RULE, Severity.HARD,
                f"{emp.name} on {fmt(d)}: load {total}% exceeds the cap "
                f"({emp.max_daily_load_pct}% + {emp.backup_stretch_pct}% backup stretch).", d, e)
        ab = ctx.absence(e, d)
        if ab is not None:
            add("WORK_DURING_ABSENCE", Category.EMPLOYEE_RULE, Severity.HARD,
                f"{emp.name} is rostered on {fmt(d)} but is {ab.value.replace('_', ' ').lower()}.", d, e)
            invalid.update(i for i, _ in day)
        if ctx.is_fixed_off(emp, d):
            add("WORK_ON_FIXED_OFF_DAY", Category.EMPLOYEE_RULE, Severity.HARD,
                f"{emp.name} is rostered on a fixed weekly off ({d:%A}, {fmt(d)}).", d, e)
            invalid.update(i for i, _ in day)

    # ── 4. rest rules ───────────────────────────────────────────────────────
    def working(e, d) -> bool:
        en = entries.get((e, d))
        if en is not None:
            return en.status == EntryStatus.WORK
        h = ctx.history.get((e, d))
        return bool(h and h.working)

    def shift_on(e, d):
        en = entries.get((e, d))
        if en is not None:
            return en.shift_id if en.status == EntryStatus.WORK else None
        h = ctx.history.get((e, d))
        return h.shift_id if h and h.working else None

    for emp in ctx.employees.values():
        pol = emp.policy
        for week in ctx.weeks():
            countable = [d for d in week if pol.holidays_count_as_rest or not ctx.employee_holiday(emp, d)]
            need = min(ctx.required_offs_in_week(emp, week), len(countable))
            offs = sum(not working(emp.id, d) for d in countable)
            if offs < need:
                add("INSUFFICIENT_WEEKLY_REST", Category.EMPLOYEE_RULE, Severity.HARD,
                    f"{emp.name} has {offs} off day(s) in the week of {fmt(week_start(week[0]))}; "
                    f"at least {need} required.", week[0], emp.id, week=week_start(week[0]).isoformat())
        streak, start = 0, ctx.first_day - timedelta(days=pol.max_consecutive_work_days)
        d = start
        while d <= ctx.last_day:
            streak = streak + 1 if working(emp.id, d) else 0
            if streak == pol.max_consecutive_work_days + 1 and d >= ctx.first_day:
                add("MAX_CONSECUTIVE_EXCEEDED", Category.EMPLOYEE_RULE, Severity.HARD,
                    f"{emp.name} works more than {pol.max_consecutive_work_days} consecutive days "
                    f"(through {fmt(d)}).", d, emp.id)
            d += timedelta(days=1)
        for d in ctx.days:
            s_prev, s_now = shift_on(emp.id, d - timedelta(days=1)), shift_on(emp.id, d)
            if s_prev is not None and s_now is not None and s_prev in ctx.shifts and s_now in ctx.shifts \
                    and not ctx.rest_gap_ok(emp, s_prev, s_now):
                add("MIN_REST_VIOLATED", Category.EMPLOYEE_RULE, Severity.HARD,
                    f"{emp.name}: {ctx.shifts[s_prev].code} shift on {fmt(d - timedelta(days=1))} followed by "
                    f"{ctx.shifts[s_now].code} on {fmt(d)} leaves less than {pol.min_rest_hours}h rest.",
                    d, emp.id)

    # ── 5. coverage ─────────────────────────────────────────────────────────
    staffed_by: dict[tuple[int, date], dict[int, Role]] = defaultdict(dict)
    for i, du in enumerate(roster.duties):
        if i not in invalid:
            staffed_by[(du.slot_id, du.date)].setdefault(du.employee_id, du.duty_type)

    coverage: list[SlotCoverage] = []
    sum_req = sum_met = 0
    for slot in problem.slots:
        bp = ctx.bps.get(slot.brand_process_id)
        for d in ctx.days:
            req = ctx.required(slot.id, d)
            people = staffed_by.get((slot.id, d), {})
            staffed = len(people)                      # distinct employees
            prim = sum(r == Role.PRIMARY for r in people.values())
            backup_cap = sum(
                1 for a in ctx.eligible_assignments(slot, d, Role.BACKUP)
                if a.employee_id not in people and a.employee_id in ctx.employees
                and ctx.can_work(ctx.employees[a.employee_id], d)
            )
            st = slot_status(req, staffed)
            coverage.append(SlotCoverage(slot.id, slot.brand_process_id, slot.shift_id, d, req, staffed,
                                         prim, staffed - prim, backup_cap, st))
            if req > 0:
                sum_req += req
                sum_met += min(staffed, req)
            if st in (SlotStatus.UNDERSTAFFED, SlotStatus.UNCOVERED):
                expl = _explain_gap(ctx, entries, duties_by_day, slot, d, people)
                can_work = sum(1 for p in expl if p["can_work"])
                tag = "UNAVOIDABLE" if staffed + can_work < req else "TRADE_OFF"
                label = f"{bp.label} {ctx.shifts[slot.shift_id].code}" if bp else f"slot {slot.id}"
                msg = (f"{label} on {fmt(d)}: nobody scheduled (needs {req})."
                       if st == SlotStatus.UNCOVERED else
                       f"{label} on {fmt(d)}: {staffed} of {req} staffed.")
                add("UNCOVERED_SHIFT" if st == SlotStatus.UNCOVERED else "UNDERSTAFFED_SHIFT",
                    Category.COVERAGE, Severity.HARD, msg, d, None, slot.id,
                    required=req, staffed=staffed, gap_kind=tag, people=expl)

    process_day: dict[tuple[int, date], list[SlotStatus]] = defaultdict(list)
    for c in coverage:
        process_day[(c.brand_process_id, c.date)].append(c.status)
    process_roll = {k: worst(v) for k, v in process_day.items()}
    brand_day: dict[tuple[int, date], list[SlotStatus]] = defaultdict(list)
    for (bp_id, d), st in process_roll.items():
        brand_day[(ctx.bps[bp_id].brand_id, d)].append(st)
    brand_roll = {k: worst(v) for k, v in brand_day.items()}

    # ── 6. soft preferences ─────────────────────────────────────────────────
    for emp in ctx.employees.values():
        pref_days = [d for d in ctx.days
                     if ctx.preferred_off_priority(emp, d) and working(emp.id, d)]
        if pref_days:
            add("PREFERRED_OFF_DAY_WORKED", Category.PREFERENCE, Severity.SOFT,
                f"{emp.name} works {len(pref_days)} preferred off day(s): "
                f"{', '.join(fmt(d) for d in pref_days)}.", None, emp.id,
                days=[d.isoformat() for d in pref_days])
        hol_days = [d for d in ctx.days if ctx.employee_holiday(emp, d) and working(emp.id, d)]
        if hol_days:
            add("HOLIDAY_WORKED", Category.PREFERENCE, Severity.SOFT,
                f"{emp.name} works public holiday(s) {', '.join(fmt(d) for d in hol_days)} "
                f"(earns comp-off on publish).", None, emp.id, days=[d.isoformat() for d in hol_days])
        for d in ctx.days:
            en = entries.get((emp.id, d))
            if en is None or en.status != EntryStatus.WORK:
                continue
            doing = {du.slot_id for _i, du in duties_by_day.get((emp.id, d), [])}
            for a in ctx.assignments_by_emp.get(emp.id, ()):
                if a.role != Role.PRIMARY:
                    continue
                for slot in ctx.slots_by_bp.get(a.brand_process_id, ()):
                    if slot.shift_id == en.shift_id and slot.id not in doing \
                            and ctx.required(slot.id, d) > 0 and ctx.eligible(a, slot, d):
                        add("PRIMARY_DUTY_SKIPPED", Category.PREFERENCE, Severity.SOFT,
                            f"{emp.name} works {ctx.shifts[en.shift_id].code} on {fmt(d)} but is not "
                            f"doing their primary duty {ctx.bps[a.brand_process_id].label}.",
                            d, emp.id, slot.id)

    # ── 7. master-data warnings ─────────────────────────────────────────────
    issues.extend(presolve(ctx).issues)

    if any(i.category in (Category.INTEGRITY, Category.EMPLOYEE_RULE) for i in issues):
        status = ValidationStatus.INVALID
    elif any(i.category == Category.COVERAGE for i in issues):
        status = ValidationStatus.PARTIALLY_COVERED
    else:
        status = ValidationStatus.FULLY_COVERED
    pct = round(100.0 * sum_met / sum_req, 2) if sum_req else 100.0
    return ValidationReport(status, coverage, process_roll, brand_roll, issues, pct)


def _explain_gap(ctx: Context, entries, duties_by_day, slot, d, people) -> list[dict]:
    """Why each eligible-but-not-scheduled person is not covering this slot."""
    out = []
    for a in ctx.eligible_assignments(slot, d):
        e = a.employee_id
        if e in people or e not in ctx.employees:
            continue
        emp = ctx.employees[e]
        en = entries.get((e, d))
        available = False
        can_work = ctx.can_work(emp, d)
        ab = ctx.absence(e, d)
        if ab is not None:
            why = {"LEAVE": "on approved leave", "COMP_OFF": "on comp-off",
                   "UNAVAILABLE": "marked unavailable"}[ab.value]
        elif ctx.is_fixed_off(emp, d):
            why = "fixed weekly off"
        elif en is None or en.status != EntryStatus.WORK:
            status = en.status.value.replace("_", " ").lower() if en else "not rostered"
            why = f"{status} (needed for weekly rest or fairness)"
            available = True
        elif en.shift_id != slot.shift_id:
            why = f"working {ctx.shifts[en.shift_id].code} shift (one shift per day)"
            available = True
        else:
            load = sum(ctx.assignments[du.assignment_id].load_pct
                       for _i, du in duties_by_day.get((e, d), []) if du.assignment_id in ctx.assignments)
            cap = emp.max_daily_load_pct + (emp.backup_stretch_pct if a.role == Role.BACKUP else 0)
            if load + a.load_pct > cap:
                why = f"at load cap ({load}% + {a.load_pct}% > {cap}%)"
            else:
                why = "working the same shift with spare capacity"
                available = True
        out.append({"employee_id": e, "name": emp.name, "role": a.role.value,
                    "reason": why, "available": available, "can_work": can_work})
    return out


def classify(solve_status: SolveStatus, report: ValidationReport | None) -> ValidationStatus:
    """Final version status. Solver failures are never collapsed into each other."""
    if solve_status == SolveStatus.INFEASIBLE:
        return ValidationStatus.INFEASIBLE
    if solve_status in (SolveStatus.SOLVER_TIMEOUT, SolveStatus.MODEL_INVALID):
        return ValidationStatus.SOLVER_TIMEOUT if solve_status == SolveStatus.SOLVER_TIMEOUT \
            else ValidationStatus.INVALID
    assert report is not None
    return report.status
