"""Ranked resolution suggestions for a coverage gap (slot + date).

Candidates are employees with an effective PRIMARY or BACKUP assignment for the
slot's brand-process that allows the slot's shift and who are not absent / on a
fixed off day.  Each candidate gets one concrete action:

ADD_DUTY         already working the same shift with load headroom
WORK_ON_OFF_DAY  currently off; works this day, with a proposed swap-off day in
                 the same week that does not open a new gap
CHANGE_SHIFT     working another shift; moving drops their current duties
                 (impact listed, including any new gaps it would create)

Every suggestion is re-checked by the validator when the manager applies it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .calendar import Context, week_start
from .types import EntryStatus, Problem, Role, Roster


@dataclass(frozen=True)
class Suggestion:
    employee_id: int
    name: str
    action: str
    assignment_id: int
    role: str
    score: int
    reasons: tuple[str, ...]
    impact: tuple[str, ...] = ()
    swap_off_date: date | None = None


def suggest(problem: Problem, roster: Roster, slot_id: int, d: date, limit: int = 5) -> list[Suggestion]:
    ctx = Context(problem)
    slot = ctx.slots[slot_id]
    entries = roster.entry_map()
    by_day = roster.duties_by_day()
    staffed: dict[tuple[int, date], set[int]] = defaultdict(set)
    backup_counts: dict[int, int] = defaultdict(int)
    for du in roster.duties:
        staffed[(du.slot_id, du.date)].add(du.employee_id)
        if du.duty_type == Role.BACKUP:
            backup_counts[du.employee_id] += 1
    already = staffed.get((slot_id, d), set())
    primary_pods = {ctx.employees[a.employee_id].pod_id
                    for a in ctx.eligible_assignments(slot, d, Role.PRIMARY) if a.employee_id in ctx.employees}

    def would_gap(slot2: int, day: date, removing: int) -> bool:
        req = ctx.required(slot2, day)
        return req > 0 and len(staffed.get((slot2, day), set()) - {removing}) < req

    def rest_ok(e: int, shift_id: int) -> bool:
        emp = ctx.employees[e]
        for nd, before in ((d - timedelta(days=1), True), (d + timedelta(days=1), False)):
            ne = entries.get((e, nd))
            if ne is None or ne.status != EntryStatus.WORK:
                continue
            ok = ctx.rest_gap_ok(emp, ne.shift_id, shift_id) if before else ctx.rest_gap_ok(emp, shift_id, ne.shift_id)
            if not ok:
                return False
        return True

    out: list[Suggestion] = []
    for a in ctx.eligible_assignments(slot, d):
        e = a.employee_id
        emp = ctx.employees.get(e)
        if emp is None or e in already or not ctx.can_work(emp, d):
            continue
        en = entries.get((e, d))
        reasons: list[str] = []
        impact: list[str] = []
        score = 0
        swap = None
        day_duties = by_day.get((e, d), [])
        load = sum(ctx.assignments[du.assignment_id].load_pct for du in day_duties
                   if du.assignment_id in ctx.assignments)
        cap = emp.max_daily_load_pct + (emp.backup_stretch_pct if a.role == Role.BACKUP else 0)

        if en is not None and en.status == EntryStatus.WORK and en.shift_id == slot.shift_id:
            if load + a.load_pct > cap:
                continue
            action, score = "ADD_DUTY", 100
            reasons.append(f"already on {ctx.shifts[slot.shift_id].code} shift; load {load}% -> {load + a.load_pct}%")
        elif en is not None and en.status == EntryStatus.WORK:
            if a.load_pct > cap or not rest_ok(e, slot.shift_id):
                continue
            action, score = "CHANGE_SHIFT", 40
            reasons.append(f"currently on {ctx.shifts[en.shift_id].code}; would move to {ctx.shifts[slot.shift_id].code}")
            for du in day_duties:
                lbl = f"{ctx.bps[du.brand_process_id].label} {ctx.shifts[du.shift_id].code}"
                if would_gap(du.slot_id, d, e):
                    impact.append(f"opens a gap on {lbl}")
                    score -= 25
                else:
                    impact.append(f"drops {lbl} (still covered)")
        else:
            if not rest_ok(e, slot.shift_id):
                continue
            action, score = "WORK_ON_OFF_DAY", 30
            if ctx.employee_holiday(emp, d):
                reasons.append("public holiday for this employee - earns a comp-off")
                score -= 10
            # Find a swap-off day in the same week that keeps everything covered.
            ws = week_start(d)
            for i in range(7):
                w = ws + timedelta(days=i)
                we = entries.get((e, w))
                if w == d or we is None or we.status != EntryStatus.WORK or ctx.is_fixed_off(emp, w):
                    continue
                if all(not would_gap(du.slot_id, w, e) for du in by_day.get((e, w), [])):
                    swap = w
                    break
            if swap:
                score += 40
                reasons.append(f"swap weekly off to {swap:%a %d %b} (their duties that day stay covered)")
            else:
                impact.append("no gap-free swap day this week - weekly rest must be re-checked")

        if a.role == Role.PRIMARY:
            score += 15
            reasons.append("primary on this process")
        else:
            reasons.append("trained backup")
        if emp.pod_id in primary_pods:
            score += 10
            reasons.append("same pod")
        score += max(0, 10 - 2 * backup_counts[e])
        out.append(Suggestion(e, emp.name, action, a.id, a.role.value, score,
                              tuple(reasons), tuple(impact), swap))

    out.sort(key=lambda s: (-s.score, s.employee_id))
    return out[:limit]
