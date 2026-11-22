"""CP-SAT roster model.

Decision variables
------------------
x[e,d,slot]   1 if employee e performs the slot (brand_process_shift) on day d.
              Created only for *candidates*: e holds an assignment effective on d
              for the slot's brand-process, the assignment allows the slot's shift
              and the slot is required that day.  Because an employee holds at
              most one assignment per brand-process per date, each candidate maps
              to exactly one assignment -> duty_type (role) and load_pct.
work[e,d]     1 if e works on d.
sh[e,d,s]     1 if e's single shift on d is s.
short[slot,d] unmet headcount (0..required).

Hard constraints (never relaxed)
--------------------------------
* duty only on a work day, in the day's shift; exactly one shift when working;
  no work day without a duty
* absence (leave / comp-off / unavailable) and fixed off days -> no work
* load cap on primary duties; cap + backup stretch on all duties
* minimum offs per Monday-Sunday week, maximum consecutive work days,
  minimum rest hours between consecutive shifts (month boundary uses history)
* locked rows are fixed (enforced through *assumption literals*, so an
  infeasible lock set is reported with the exact rows that clash)

Coverage is soft through ``short`` with a dominant penalty, so the model is
always feasible unless locked rows contradict hard rules.  A proven-infeasible
model returns INFEASIBLE; a limit reached with no solution returns
SOLVER_TIMEOUT - the two are never conflated.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ortools.sat.python import cp_model

from .calendar import Context
from .presolve import PresolveReport, presolve
from .types import (
    AbsenceKind,
    Assignment,
    EntryStatus,
    Problem,
    Role,
    Roster,
    RosterDuty,
    RosterEntry,
    Slot,
    SolveStatus,
    Source,
)

Key = tuple[int, date]  # (employee_id, date)


@dataclass(frozen=True)
class Lock:
    """A fixed (employee, day): its entry and its exact duty set."""
    entry: RosterEntry
    duties: tuple[RosterDuty, ...] = ()


@dataclass(frozen=True)
class LockConflict:
    employee_id: int
    date: date
    reason: str


@dataclass
class SolveResult:
    status: SolveStatus
    roster: Roster | None
    presolve: PresolveReport
    shortfall: dict[tuple[int, date], int] = field(default_factory=dict)
    lock_conflicts: list[LockConflict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Cand:
    assignment: Assignment
    slot: Slot


def off_status(ctx: Context, employee_id: int, d: date) -> EntryStatus:
    """Label for a non-working day: absence > employee public holiday > weekly off."""
    ab = ctx.absence(employee_id, d)
    if ab is not None:
        return {AbsenceKind.LEAVE: EntryStatus.LEAVE, AbsenceKind.COMP_OFF: EntryStatus.COMP_OFF,
                AbsenceKind.UNAVAILABLE: EntryStatus.UNAVAILABLE}[ab]
    emp = ctx.employees[employee_id]
    if ctx.employee_holiday(emp, d):
        return EntryStatus.HOLIDAY
    return EntryStatus.WEEKLY_OFF


def solve(
    problem: Problem,
    locks: dict[Key, Lock] | None = None,
    previous: Roster | None = None,
    stability_keys: set[Key] | None = None,
) -> SolveResult:
    ctx = Context(problem)
    pre = presolve(ctx)
    locks = locks or {}
    stability_keys = stability_keys or set()
    W = problem.settings.weights
    m = cp_model.CpModel()

    # ── candidates ──────────────────────────────────────────────────────────
    cands: dict[Key, dict[int, _Cand]] = defaultdict(dict)  # key -> slot_id -> cand
    for (slot_id, d), _req in ctx.requirements.items():
        slot = ctx.slots[slot_id]
        for a in ctx.eligible_assignments(slot, d):
            emp = ctx.employees.get(a.employee_id)
            if emp and ctx.can_work(emp, d):
                cands[(a.employee_id, d)].setdefault(slot_id, _Cand(a, slot))

    direct_conflicts: list[LockConflict] = []
    for key, lock in locks.items():
        if key[0] not in ctx.employees:
            direct_conflicts.append(LockConflict(*key, "employee is inactive"))
            continue
        for du in lock.duties:
            slot = ctx.slots.get(du.slot_id)
            a = ctx.assignments.get(du.assignment_id)
            if slot is None or a is None or a.employee_id != key[0] or not ctx.eligible(a, slot, key[1]):
                direct_conflicts.append(LockConflict(
                    *key, f"locked duty on slot {du.slot_id} has no valid assignment for this date/shift"))
                continue
            cands[key].setdefault(slot.id, _Cand(a, slot))
        if lock.entry.status == EntryStatus.WORK and not lock.duties:
            direct_conflicts.append(LockConflict(*key, "locked WORK day has no duties"))
    if direct_conflicts:
        return SolveResult(SolveStatus.INFEASIBLE, None, pre, lock_conflicts=direct_conflicts)

    # ── variables ───────────────────────────────────────────────────────────
    x: dict[tuple[int, date, int], cp_model.IntVar] = {}
    work: dict[Key, cp_model.IntVar] = {}
    sh: dict[tuple[int, date, int], cp_model.IntVar] = {}
    shk: dict[Key, dict[int, cp_model.IntVar]] = defaultdict(dict)  # (e,d) -> shift -> var

    for emp in ctx.employees.values():
        for d in ctx.days:
            key = (emp.id, d)
            w = work[key] = m.NewBoolVar(f"w_{emp.id}_{d:%d}")
            day_cands = cands.get(key, {})
            if not day_cands:
                m.Add(w == 0)
                continue
            for slot_id, c in day_cands.items():
                x[(emp.id, d, slot_id)] = m.NewBoolVar(f"x_{emp.id}_{d:%d}_{slot_id}")
            for s in sorted({c.slot.shift_id for c in day_cands.values()}):
                sh[(emp.id, d, s)] = shk[key][s] = m.NewBoolVar(f"s_{emp.id}_{d:%d}_{s}")
            m.Add(sum(shk[key].values()) == w)                                    # one shift
            xs = []
            for slot_id, c in day_cands.items():
                xv = x[(emp.id, d, slot_id)]
                xs.append(xv)
                m.Add(xv <= sh[(emp.id, d, c.slot.shift_id)])             # duty in day's shift
            m.Add(w <= sum(xs))                                            # no idle work day
            prim = [(c.assignment.load_pct, x[(emp.id, d, sid)])
                    for sid, c in day_cands.items() if c.assignment.role == Role.PRIMARY]
            if prim:
                m.Add(sum(l * v for l, v in prim) <= emp.max_daily_load_pct)
            m.Add(sum(c.assignment.load_pct * x[(emp.id, d, sid)] for sid, c in day_cands.items())
                  <= emp.max_daily_load_pct + emp.backup_stretch_pct)
            if not ctx.can_work(emp, d):
                m.Add(w == 0)                                              # absence / fixed off

    # ── rest rules ──────────────────────────────────────────────────────────
    for emp in ctx.employees.values():
        pol = emp.policy
        for week in ctx.weeks():
            countable = [d for d in week
                         if pol.holidays_count_as_rest or not ctx.employee_holiday(emp, d)]
            need = min(ctx.required_offs_in_week(emp, week), len(countable))
            if need > 0:
                m.Add(sum(1 - work[(emp.id, d)] for d in countable) >= need)

        k = pol.max_consecutive_work_days
        prior = ctx.history_streak_before_month(emp)
        seq: list = [1] * min(prior, k) + [work[(emp.id, d)] for d in ctx.days]
        for i in range(len(seq) - k):
            window = seq[i:i + k + 1]
            if any(not isinstance(v, int) for v in window):
                m.Add(sum(window) <= k)

        prev_shift = ctx.history_shift_before_month(emp)
        if prev_shift is not None:
            for s, v in shk.get((emp.id, ctx.first_day), {}).items():
                if not ctx.rest_gap_ok(emp, prev_shift, s):
                    m.Add(v == 0)
        for d in ctx.days[:-1]:
            nd = d + timedelta(days=1)
            for s1, v1 in shk.get((emp.id, d), {}).items():
                for s2, v2 in shk.get((emp.id, nd), {}).items():
                    if not ctx.rest_gap_ok(emp, s1, s2):
                        m.Add(v1 + v2 <= 1)

    # ── coverage ────────────────────────────────────────────────────────────
    by_slot_day: dict[tuple[int, date], list] = defaultdict(list)
    for (e, d, slot_id), v in x.items():
        by_slot_day[(slot_id, d)].append(v)
    short: dict[tuple[int, date], cp_model.IntVar] = {}
    for (slot_id, d), req in ctx.requirements.items():
        sv = short[(slot_id, d)] = m.NewIntVar(0, req, f"short_{slot_id}_{d:%d}")
        m.Add(sum(by_slot_day.get((slot_id, d), [])) + sv >= req)

    # ── locks (assumption literals) ─────────────────────────────────────────
    lock_lits: dict[int, Key] = {}
    for key, lock in locks.items():
        lit = m.NewBoolVar(f"lock_{key[0]}_{key[1]:%d}")
        lock_lits[lit.Index()] = key
        e, d = key
        if lock.entry.status == EntryStatus.WORK:
            m.Add(work[key] == 1).OnlyEnforceIf(lit)
            sv = sh.get((e, d, lock.entry.shift_id))
            if sv is None:
                m.Add(work[key] == 0).OnlyEnforceIf(lit)  # shift impossible -> contradiction
            else:
                m.Add(sv == 1).OnlyEnforceIf(lit)
            locked_slots = {du.slot_id for du in lock.duties}
            for slot_id in cands.get(key, {}):
                m.Add(x[(e, d, slot_id)] == int(slot_id in locked_slots)).OnlyEnforceIf(lit)
        else:
            m.Add(work[key] == 0).OnlyEnforceIf(lit)
        m.AddAssumption(lit)

    # ── objective ───────────────────────────────────────────────────────────
    terms = [W.shortfall * v for v in short.values()]
    for emp in ctx.employees.values():
        weekend_offs = []
        for d in ctx.days:
            key = (emp.id, d)
            w = work[key]
            available = ctx.can_work(emp, d)
            holiday = ctx.employee_holiday(emp, d)
            if available and cands.get(key) and not holiday:
                terms.append(W.excess_off * (1 - w))
            if holiday:
                terms.append(W.holiday_work * w)
            prio = ctx.preferred_off_priority(emp, d)
            if prio:
                terms.append(W.preferred_off * prio * w)
            if d.weekday() >= 5 and available:
                weekend_offs.append(1 - w)
            for slot_id, c in cands.get(key, {}).items():
                xv = x[(emp.id, d, slot_id)]
                if c.assignment.role == Role.BACKUP:
                    terms.append(W.backup_activation * xv)
                elif (slot_id, d) in ctx.requirements:
                    # primary continuity: working the shift but skipping own duty
                    terms.append(W.primary_continuity * (sh[(emp.id, d, c.slot.shift_id)] - xv))
        target = problem.settings.weekend_off_target
        if target and weekend_offs:
            deficit = m.NewIntVar(0, target, f"wkdef_{emp.id}")
            m.Add(deficit >= target - sum(weekend_offs))
            terms.append(W.weekend_fairness * deficit)

    if previous is not None and stability_keys:
        prev_entries = previous.entry_map()
        prev_duties = previous.duties_by_day()
        for key in stability_keys:
            pe = prev_entries.get(key)
            if pe is None or key not in work:
                continue
            e, d = key
            if pe.status == EntryStatus.WORK:
                sv = sh.get((e, d, pe.shift_id))
                terms.append(W.stability * (1 - sv) if sv is not None else W.stability)
            else:
                terms.append(W.stability * work[key])
            had = {du.slot_id for du in prev_duties.get(key, [])}
            for slot_id in cands.get(key, {}):
                xv = x[(e, d, slot_id)]
                terms.append(W.stability * ((1 - xv) if slot_id in had else xv))

    m.Minimize(sum(terms))

    # ── solve ───────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    prm = solver.parameters
    prm.random_seed = problem.settings.seed
    prm.num_workers = 1                      # single worker => reproducible output
    prm.linearization_level = 2              # full LP relaxation: proves optimality fast
    prm.max_deterministic_time = problem.settings.deterministic_time
    prm.max_time_in_seconds = problem.settings.wall_time_limit
    code = solver.Solve(m)

    stats = {"cp_sat_status": str(code), "num_candidates": len(x), "num_locked": len(locks)}
    try:
        stats["cp_sat_status"] = solver.status_name(code)
        stats["wall_time_s"] = round(solver.wall_time, 3)
        stats["deterministic_time"] = round(solver.deterministic_time, 3)
    except (RuntimeError, AttributeError):  # no response available (e.g. aborted solve)
        pass

    if code == cp_model.INFEASIBLE:
        culprits = [lock_lits[i] for i in solver.SufficientAssumptionsForInfeasibility()
                    if i in lock_lits]
        conflicts = [LockConflict(e, d, "locked row contradicts a mandatory rule "
                                        "(absence, rest, shift or load)") for e, d in culprits]
        return SolveResult(SolveStatus.INFEASIBLE, None, pre, lock_conflicts=conflicts, stats=stats)
    if code == cp_model.UNKNOWN:
        return SolveResult(SolveStatus.SOLVER_TIMEOUT, None, pre, stats=stats)
    if code == cp_model.MODEL_INVALID:
        return SolveResult(SolveStatus.MODEL_INVALID, None, pre, stats=stats)

    stats["objective"] = solver.ObjectiveValue()
    stats["best_bound"] = solver.BestObjectiveBound()

    # ── extract roster ──────────────────────────────────────────────────────
    prev_entries = previous.entry_map() if previous else {}
    prev_duty_slots = ({k: {du.slot_id: du for du in v} for k, v in previous.duties_by_day().items()}
                       if previous else {})
    roster = Roster()
    for emp in ctx.employees.values():
        for d in ctx.days:
            key = (emp.id, d)
            lock = locks.get(key)
            if lock is not None:
                # Locked rows are reproduced verbatim (the solver proved they fit).
                roster.entries.append(lock.entry)
                roster.duties.extend(lock.duties)
                continue
            if solver.Value(work[key]):
                shift_id = next(s for s, v in shk[key].items() if solver.Value(v))
                status = EntryStatus.WORK
            else:
                shift_id, status = None, off_status(ctx, emp.id, d)
            if key in stability_keys:
                pe = prev_entries.get(key)
                same = pe is not None and pe.status == status and pe.shift_id == shift_id
                src, locked = (pe.source if same else Source.REOPT), False
            else:
                src, locked = Source.AUTO, False
            roster.entries.append(RosterEntry(emp.id, d, status, shift_id, src, locked))
            if status != EntryStatus.WORK:
                continue
            for slot_id, c in cands.get(key, {}).items():
                if not solver.Value(x[(emp.id, d, slot_id)]):
                    continue
                if key in stability_keys:
                    prev = prev_duty_slots.get(key, {}).get(slot_id)
                    dsrc = prev.source if prev is not None else Source.REOPT
                else:
                    dsrc = Source.AUTO
                roster.duties.append(RosterDuty(
                    emp.id, d, slot_id, c.slot.brand_process_id, c.slot.shift_id,
                    c.assignment.id, c.assignment.role, dsrc, False,
                ))

    shortfall = {k: solver.Value(v) for k, v in short.items() if solver.Value(v) > 0}
    status = SolveStatus.OPTIMAL if code == cp_model.OPTIMAL else SolveStatus.FEASIBLE
    return SolveResult(status, roster, pre, shortfall=shortfall, stats=stats)
