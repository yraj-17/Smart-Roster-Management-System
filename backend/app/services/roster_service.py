"""Roster versions: generation, cloning, validated edits, publishing, re-optimisation,
diffs, views and export.

Rules enforced here (on top of the database constraints):
* Only DRAFT versions are editable; PUBLISHED / SUPERSEDED / ARCHIVED are immutable.
  Editing a published roster means cloning it into a new draft first.
* Day edits replace an employee-day atomically: duties are deleted *before* the
  entry's status/shift changes, inside one transaction, so the WORK-only FK holds.
* Structural problems (shift clash, no eligible assignment, load cap, working on an
  approved absence) are rejected with 409.  Rest-rule breaches (weekly rest,
  consecutive days, rest hours) are allowed but flag the version INVALID, which
  blocks publishing until fixed.
* Every edit is marked MANUAL + locked (preserved by re-optimisation) and audited.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import models as m
from app.errors import Conflict, DomainError, NotFound
from app.scheduling import affected_scope, generate, regenerate_window, suggest, validate
from app.scheduling import types as t
from app.scheduling.calendar import Context, month_days
from app.scheduling.reoptimize import diff_rosters
from app.scheduling.solver import off_status

from . import audit
from .engine_adapter import load_problem, load_roster, month_bounds, persist_outcome
from .validation_service import ensure_fresh, revalidate

EDITABLE = ("DRAFT",)
NO_ROSTER = ("INFEASIBLE", "SOLVER_TIMEOUT")


# ───────────────────────────── helpers ─────────────────────────────
def get_version(s: Session, version_id: int) -> m.RosterVersion:
    v = s.get(m.RosterVersion, version_id)
    if v is None:
        raise NotFound(f"Roster version {version_id} not found")
    return v


def version_dict(v: m.RosterVersion) -> dict:
    d = audit.row_dict(v, exclude=())
    d["year"], d["month"] = v.plan.year, v.plan.month
    return d


def require_draft(v: m.RosterVersion) -> None:
    if v.status not in EDITABLE:
        raise Conflict(f"Version #{v.version_no} is {v.status} and cannot be edited. Clone it into a new draft first.",
                       code="version_immutable")
    if v.validation_status in NO_ROSTER:
        raise Conflict("This version has no roster (solver did not produce one).", code="no_roster")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Lookups:
    """Display names for ids (one query per table)."""

    def __init__(self, s: Session):
        self.employees = {e.id: e for e in s.scalars(select(m.Employee))}
        self.pods = {p.id: p for p in s.scalars(select(m.Pod))}
        self.shifts = {x.id: x for x in s.scalars(select(m.Shift))}
        self.brands = {b.id: b for b in s.scalars(select(m.Brand))}
        self.processes = {p.id: p for p in s.scalars(select(m.Process))}
        self.bps = {b.id: b for b in s.scalars(select(m.BrandProcess))}
        self.slots = {x.id: x for x in s.scalars(select(m.BrandProcessShift))}

    def bp_label(self, bp_id: int) -> str:
        bp = self.bps[bp_id]
        return f"{self.brands[bp.brand_id].name} / {self.processes[bp.process_id].code}"

    def slot_info(self, slot_id: int) -> dict:
        sl = self.slots[slot_id]
        bp = self.bps[sl.brand_process_id]
        return {"slot_id": slot_id, "brand_process_id": bp.id, "brand_id": bp.brand_id,
                "brand": self.brands[bp.brand_id].name, "process": self.processes[bp.process_id].code,
                "shift": self.shifts[sl.shift_id].code, "label": f"{self.bp_label(bp.id)} {self.shifts[sl.shift_id].code}"}


# ───────────────────────────── create versions ─────────────────────────────
def generate_version(s: Session, year: int, month: int, actor: str, notes: str | None = None) -> m.RosterVersion:
    if not (1 <= month <= 12 and 2000 <= year <= 2100):
        raise DomainError("Invalid year/month")
    problem = load_problem(s, year, month)
    if not problem.employees:
        raise Conflict("There are no active employees to schedule.")
    outcome = generate(problem)
    v = persist_outcome(s, problem, outcome, kind="GENERATED", created_by=actor, params={"reason": notes})
    v.notes = notes
    s.commit()
    return v


def clone_version(s: Session, src: m.RosterVersion, actor: str, reason: str | None = None) -> m.RosterVersion:
    if src.validation_status in NO_ROSTER:
        raise Conflict("Cannot clone a version without a roster.")
    next_no = (s.scalar(select(func.max(m.RosterVersion.version_no))
                        .where(m.RosterVersion.plan_id == src.plan_id)) or 0) + 1
    v = m.RosterVersion(plan_id=src.plan_id, version_no=next_no, parent_version_id=src.id, kind="MANUAL_CLONE",
                        status="DRAFT", validation_status="STALE", created_by=actor, notes=reason,
                        params={"cloned_from": src.id})
    s.add(v)
    s.flush()
    id_map = {}
    old_entries = list(s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == src.id)))
    new_entries = []
    for e in old_entries:
        ne = m.RosterEntry(version_id=v.id, employee_id=e.employee_id, date=e.date, status=e.status,
                           shift_id=e.shift_id, source=e.source, is_locked=e.is_locked, note=e.note)
        new_entries.append((e.id, ne))
    s.add_all([ne for _, ne in new_entries])
    s.flush()
    id_map = {old: ne.id for old, ne in new_entries}
    s.add_all([
        m.RosterDuty(version_id=v.id, entry_id=id_map[d.entry_id], employee_id=d.employee_id, date=d.date,
                     shift_id=d.shift_id, entry_status="WORK", brand_process_shift_id=d.brand_process_shift_id,
                     brand_process_id=d.brand_process_id, assignment_id=d.assignment_id, duty_type=d.duty_type,
                     source=d.source, is_locked=d.is_locked)
        for d in s.scalars(select(m.RosterDuty).where(m.RosterDuty.version_id == src.id))
    ])
    s.flush()
    # Carry acknowledgements of still-present conflicts into the clone.
    acks = {(c.type, c.date, c.employee_id, c.brand_process_shift_id): c
            for c in s.scalars(select(m.RosterConflict).where(m.RosterConflict.version_id == src.id,
                                                              m.RosterConflict.status == "ACKNOWLEDGED"))}
    revalidate(s, v)
    for c in s.scalars(select(m.RosterConflict).where(m.RosterConflict.version_id == v.id)):
        src_c = acks.get((c.type, c.date, c.employee_id, c.brand_process_shift_id))
        if src_c is not None and c.status == "OPEN":
            c.status, c.ack_reason, c.ack_by, c.ack_at = "ACKNOWLEDGED", src_c.ack_reason, src_c.ack_by, src_c.ack_at
    audit.log(s, actor, "roster_version", v.id, "clone", after={"from_version": src.id}, reason=reason,
              version_id=v.id)
    s.commit()
    return v


# ───────────────────────────── edits ─────────────────────────────
def _entry_snapshot(s: Session, entry: m.RosterEntry) -> dict:
    duties = s.scalars(select(m.RosterDuty).where(m.RosterDuty.entry_id == entry.id)).all()
    return {"status": entry.status, "shift_id": entry.shift_id, "source": entry.source,
            "slot_ids": sorted(d.brand_process_shift_id for d in duties)}


def _entry(s: Session, version: m.RosterVersion, employee_id: int, d: date) -> m.RosterEntry:
    e = s.scalar(select(m.RosterEntry).where(m.RosterEntry.version_id == version.id,
                                             m.RosterEntry.employee_id == employee_id, m.RosterEntry.date == d))
    if e is None:
        raise NotFound(f"No roster entry for employee {employee_id} on {d}")
    return e


def replace_day(s: Session, version: m.RosterVersion, entry: m.RosterEntry, status: str, shift_id: int | None,
                slot_ids: list[int], note: str | None, actor: str, ctx: Context | None = None,
                reason: str | None = None) -> None:
    """Validate and atomically replace one employee-day. Does not commit or re-validate."""
    require_draft(version)
    if entry.version_id != version.id:
        raise NotFound("Entry does not belong to this version")
    ctx = ctx or Context(load_problem(s, version.plan.year, version.plan.month))
    d = entry.date
    emp = ctx.employees.get(entry.employee_id)
    if emp is None:
        raise Conflict("Employee is inactive.")
    new_duties: list[tuple[t.Slot, t.Assignment]] = []
    if status == "WORK":
        ab = ctx.absence(emp.id, d)
        if ab is not None:
            raise Conflict(f"{emp.name} is on {ab.value.replace('_', ' ').lower()} on {d}; cancel or change the "
                           f"absence before rostering them.", code="employee_absent")
        if shift_id not in ctx.shifts:
            raise NotFound(f"Shift {shift_id} not found")
        prim = total = 0
        seen_bp = set()
        for sid in slot_ids:
            slot = ctx.slots.get(sid)
            if slot is None or not slot.active:
                raise Conflict(f"Slot {sid} does not exist or is inactive.")
            if slot.shift_id != shift_id:
                raise Conflict(f"{ctx.bps[slot.brand_process_id].label} runs on {ctx.shifts[slot.shift_id].code}, "
                               f"but the day's shift is {ctx.shifts[shift_id].code}. An employee works one shift "
                               f"per day.", code="shift_clash")
            if slot.brand_process_id in seen_bp:
                raise Conflict("Two duties for the same brand-process on one day.", code="duplicate_duty")
            seen_bp.add(slot.brand_process_id)
            a = ctx.assignment_for(emp.id, slot.brand_process_id, d)
            if a is None or not ctx.eligible(a, slot, d):
                raise Conflict(f"{emp.name} has no assignment for {ctx.bps[slot.brand_process_id].label} "
                               f"{ctx.shifts[slot.shift_id].code} on {d}.", code="not_eligible")
            total += a.load_pct
            prim += a.load_pct if a.role == t.Role.PRIMARY else 0
            new_duties.append((slot, a))
        if prim > emp.max_daily_load_pct or total > emp.max_daily_load_pct + emp.backup_stretch_pct:
            raise Conflict(f"{emp.name}'s load would be {total}% (primary {prim}%), above the cap of "
                           f"{emp.max_daily_load_pct}% + {emp.backup_stretch_pct}% backup stretch.",
                           code="load_cap")

    before = _entry_snapshot(s, entry)
    # 1) remove duties, 2) change the entry, 3) add duties — one transaction.
    s.execute(delete(m.RosterDuty).where(m.RosterDuty.entry_id == entry.id))
    s.flush()
    entry.status, entry.shift_id, entry.note = status, shift_id, note
    entry.source, entry.is_locked = "MANUAL", True
    s.flush()
    for slot, a in new_duties:
        s.add(m.RosterDuty(version_id=version.id, entry_id=entry.id, employee_id=entry.employee_id, date=d,
                           shift_id=shift_id, entry_status="WORK", brand_process_shift_id=slot.id,
                           brand_process_id=slot.brand_process_id, assignment_id=a.id, duty_type=a.role.value,
                           source="MANUAL", is_locked=True))
    s.flush()
    audit.log(s, actor, "roster_entry", entry.id, "edit_day", before=before, after=_entry_snapshot(s, entry),
              reason=reason or note, version_id=version.id)


def day_result(s: Session, version: m.RosterVersion, entry: m.RosterEntry) -> dict:
    duties = s.scalars(select(m.RosterDuty).where(m.RosterDuty.entry_id == entry.id)).all()
    issues = s.scalars(select(m.RosterConflict).where(
        m.RosterConflict.version_id == version.id, m.RosterConflict.status == "OPEN",
        m.RosterConflict.date == entry.date)).all()
    lk = Lookups(s)
    return {
        "version": version_dict(version),
        "entry": audit.row_dict(entry),
        "duties": [{**audit.row_dict(d), **lk.slot_info(d.brand_process_shift_id)} for d in duties],
        "issues_on_day": [audit.row_dict(i) for i in issues
                          if i.employee_id in (None, entry.employee_id) and i.category != "PREFERENCE"],
    }


def edit_day(s: Session, version: m.RosterVersion, entry_id: int, status: str, shift_id: int | None,
             slot_ids: list[int], note: str | None, actor: str) -> dict:
    entry = s.get(m.RosterEntry, entry_id)
    if entry is None or entry.version_id != version.id:
        raise NotFound("Entry not found in this version")
    replace_day(s, version, entry, status, shift_id, slot_ids, note, actor)
    revalidate(s, version)
    s.commit()
    return day_result(s, version, entry)


def add_duty(s: Session, version: m.RosterVersion, employee_id: int, d: date, slot_id: int, actor: str) -> dict:
    require_draft(version)
    entry = _entry(s, version, employee_id, d)
    slot = s.get(m.BrandProcessShift, slot_id)
    if slot is None:
        raise NotFound(f"Slot {slot_id} not found")
    if entry.status == "WORK":
        if entry.shift_id != slot.shift_id:
            raise Conflict("The employee already works a different shift that day. Change the day's shift "
                           "instead (one shift per day).", code="shift_clash")
        current = [x.brand_process_shift_id for x in
                   s.scalars(select(m.RosterDuty).where(m.RosterDuty.entry_id == entry.id))]
        replace_day(s, version, entry, "WORK", entry.shift_id, current + [slot_id], entry.note, actor,
                    reason="add duty")
    else:
        replace_day(s, version, entry, "WORK", slot.shift_id, [slot_id], entry.note, actor, reason="add duty")
    revalidate(s, version)
    s.commit()
    return day_result(s, version, entry)


def remove_duty(s: Session, version: m.RosterVersion, duty_id: int, actor: str) -> dict:
    require_draft(version)
    duty = s.get(m.RosterDuty, duty_id)
    if duty is None or duty.version_id != version.id:
        raise NotFound("Duty not found in this version")
    entry = s.get(m.RosterEntry, duty.entry_id)
    remaining = [x.brand_process_shift_id for x in
                 s.scalars(select(m.RosterDuty).where(m.RosterDuty.entry_id == entry.id, m.RosterDuty.id != duty_id))]
    ctx = Context(load_problem(s, version.plan.year, version.plan.month))
    if remaining:
        replace_day(s, version, entry, "WORK", entry.shift_id, remaining, entry.note, actor, ctx, "remove duty")
    else:
        replace_day(s, version, entry, off_status(ctx, entry.employee_id, entry.date).value, None, [],
                    entry.note, actor, ctx, "remove last duty")
    revalidate(s, version)
    s.commit()
    return day_result(s, version, entry)


# ───────────────────────────── conflicts ─────────────────────────────
def acknowledge(s: Session, conflict: m.RosterConflict, reason: str, actor: str) -> m.RosterConflict:
    if conflict.category in ("INTEGRITY", "EMPLOYEE_RULE", "SOLVER"):
        raise Conflict("Rule violations must be fixed, not acknowledged.", code="not_acknowledgeable")
    if conflict.status != "OPEN":
        raise Conflict(f"Conflict is already {conflict.status}.")
    before = audit.row_dict(conflict)
    conflict.status, conflict.ack_reason, conflict.ack_by, conflict.ack_at = "ACKNOWLEDGED", reason, actor, _now()
    audit.log(s, actor, "roster_conflict", conflict.id, "acknowledge", before={"status": before["status"]},
              after={"status": "ACKNOWLEDGED"}, reason=reason, version_id=conflict.version_id)
    s.commit()
    return conflict


def fresh_suggestions(s: Session, conflict: m.RosterConflict, limit: int = 5) -> list:
    v = conflict.version_id and s.get(m.RosterVersion, conflict.version_id)
    if conflict.category != "COVERAGE" or not conflict.brand_process_shift_id or not conflict.date:
        return []
    problem = load_problem(s, v.plan.year, v.plan.month)
    return suggest(problem, load_roster(s, v.id), conflict.brand_process_shift_id, conflict.date, limit)


def apply_suggestion(s: Session, conflict: m.RosterConflict, employee_id: int, action: str, actor: str) -> dict:
    version = s.get(m.RosterVersion, conflict.version_id)
    require_draft(version)
    if conflict.status == "RESOLVED":
        raise Conflict("This gap is already resolved.")
    sugg = next((x for x in fresh_suggestions(s, conflict, limit=50)
                 if x.employee_id == employee_id and x.action == action), None)
    if sugg is None:
        raise Conflict("That suggestion is no longer valid for the current roster. Refresh suggestions.",
                       code="stale_suggestion")
    ctx = Context(load_problem(s, version.plan.year, version.plan.month))
    slot = ctx.slots[conflict.brand_process_shift_id]
    entry = _entry(s, version, employee_id, conflict.date)
    why = f"apply suggestion {action} for conflict {conflict.id}"
    if action == "ADD_DUTY":
        current = [x.brand_process_shift_id for x in
                   s.scalars(select(m.RosterDuty).where(m.RosterDuty.entry_id == entry.id))]
        replace_day(s, version, entry, "WORK", entry.shift_id, current + [slot.id], entry.note, actor, ctx, why)
    else:  # WORK_ON_OFF_DAY / CHANGE_SHIFT: the day becomes this single duty
        replace_day(s, version, entry, "WORK", slot.shift_id, [slot.id], entry.note, actor, ctx, why)
        if action == "WORK_ON_OFF_DAY" and sugg.swap_off_date:
            swap = _entry(s, version, employee_id, sugg.swap_off_date)
            replace_day(s, version, swap, "WEEKLY_OFF", None, [], "swapped weekly off", actor, ctx, why)
    revalidate(s, version)
    s.refresh(conflict)
    s.commit()
    return {"conflict": audit.row_dict(conflict), "version": version_dict(version)}


# ───────────────────────────── publish / archive ─────────────────────────────
def publish(s: Session, version: m.RosterVersion, actor: str, reason: str | None = None) -> dict:
    require_draft(version)
    ensure_fresh(s, version)
    vs = version.validation_status
    if vs not in ("FULLY_COVERED", "PARTIALLY_COVERED"):
        raise Conflict(f"A {vs} roster cannot be published. Fix the hard rule violations first.",
                       code="not_publishable")
    if vs == "PARTIALLY_COVERED":
        open_gaps = s.scalars(select(m.RosterConflict).where(
            m.RosterConflict.version_id == version.id, m.RosterConflict.category == "COVERAGE",
            m.RosterConflict.status == "OPEN")).all()
        if open_gaps:
            raise Conflict(f"{len(open_gaps)} coverage gap(s) are still open. Resolve or acknowledge each one "
                           f"(with a reason) before publishing.", code="open_gaps",
                           details={"open_gap_ids": [c.id for c in open_gaps]})
    prev = s.scalar(select(m.RosterVersion).where(m.RosterVersion.plan_id == version.plan_id,
                                                  m.RosterVersion.status == "PUBLISHED"))
    if prev is not None:
        prev.status = "SUPERSEDED"
        s.flush()
        audit.log(s, actor, "roster_version", prev.id, "supersede", after={"superseded_by": version.id},
                  version_id=prev.id)
    version.status, version.published_by, version.published_at = "PUBLISHED", actor, _now()
    s.flush()
    comp = sync_comp_offs(s, version, actor)
    audit.log(s, actor, "roster_version", version.id, "publish",
              after={"validation_status": vs, "coverage_pct": float(version.coverage_pct or 0),
                     "superseded": prev.id if prev else None, "comp_offs": comp},
              reason=reason, version_id=version.id)
    s.commit()
    return {"version": version_dict(version), "superseded_version_id": prev.id if prev else None,
            "comp_offs": comp}


def sync_comp_offs(s: Session, version: m.RosterVersion, actor: str) -> dict:
    """Create PENDING credits for public-holiday work; reverse credits whose work disappeared."""
    first, last = month_bounds(version.plan.year, version.plan.month)
    ctx = Context(load_problem(s, version.plan.year, version.plan.month))
    worked_holidays = set()
    for e in s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == version.id,
                                                   m.RosterEntry.status == "WORK")):
        emp = ctx.employees.get(e.employee_id)
        if emp is not None and ctx.employee_holiday(emp, e.date):
            worked_holidays.add((e.employee_id, e.date))
    existing = {(c.employee_id, c.earned_on): c for c in s.scalars(select(m.CompOffCredit).where(
        m.CompOffCredit.source == "HOLIDAY_WORK", m.CompOffCredit.earned_on.between(first, last)))}
    out = {"created": [], "reactivated": [], "reversed": [], "consumed_but_unworked": []}
    for key in sorted(worked_holidays):
        c = existing.get(key)
        if c is None:
            c = m.CompOffCredit(employee_id=key[0], earned_on=key[1], source="HOLIDAY_WORK",
                                source_version_id=version.id, status="PENDING",
                                note=f"Worked {ctx.employee_holiday(ctx.employees[key[0]], key[1])}")
            s.add(c)
            s.flush()
            out["created"].append(c.id)
            audit.log(s, actor, "comp_off_credit", c.id, "earn", after=audit.row_dict(c), version_id=version.id)
        elif c.status == "REVERSED":
            c.status, c.source_version_id = "PENDING", version.id
            out["reactivated"].append(c.id)
            audit.log(s, actor, "comp_off_credit", c.id, "reactivate", after={"status": "PENDING"},
                      version_id=version.id)
    for key, c in existing.items():
        if key in worked_holidays:
            continue
        if c.status in ("PENDING", "AVAILABLE"):
            before = c.status
            c.status = "REVERSED"
            out["reversed"].append(c.id)
            audit.log(s, actor, "comp_off_credit", c.id, "reverse", before={"status": before},
                      after={"status": "REVERSED"}, reason="holiday work removed in published roster",
                      version_id=version.id)
        elif c.status == "CONSUMED":
            out["consumed_but_unworked"].append(c.id)
    s.flush()
    return out


def archive(s: Session, version: m.RosterVersion, actor: str) -> m.RosterVersion:
    if version.status != "DRAFT":
        raise Conflict("Only drafts can be archived; published history is kept.")
    version.status = "ARCHIVED"
    audit.log(s, actor, "roster_version", version.id, "archive", version_id=version.id)
    s.commit()
    return version


# ───────────────────────────── re-optimisation ─────────────────────────────
def reoptimize(s: Session, version: m.RosterVersion, date_from: date, date_to: date,
               employee_ids: list[int] | None, whole_window: bool, override_entry_ids: list[int],
               actor: str, reason: str | None = None) -> dict:
    if version.validation_status in NO_ROSTER:
        raise Conflict("This version has no roster to re-optimise.")
    first, last = month_bounds(version.plan.year, version.plan.month)
    if not (first <= date_from <= last and first <= date_to <= last):
        raise DomainError("The window must lie inside the version's month.")
    problem = load_problem(s, version.plan.year, version.plan.month)
    previous = load_roster(s, version.id)
    scope = None
    if not whole_window:
        if not employee_ids:
            raise DomainError("Give employee_ids (the people whose change triggered this) or set whole_window.")
        scope = affected_scope(problem, set(employee_ids))
    overrides = set()
    if override_entry_ids:
        rows = s.scalars(select(m.RosterEntry).where(m.RosterEntry.id.in_(override_entry_ids),
                                                     m.RosterEntry.version_id == version.id)).all()
        if len(rows) != len(set(override_entry_ids)):
            raise NotFound("Some override entries do not belong to this version.")
        overrides = {(r.employee_id, r.date) for r in rows}
    outcome = regenerate_window(problem, previous, date_from, date_to, scope, overrides)
    params = {"reason": reason, "window": [date_from.isoformat(), date_to.isoformat()],
              "scope": sorted(scope) if scope is not None else "whole_window",
              "override_manual": sorted(f"{e}:{d.isoformat()}" for e, d in overrides)}
    new = persist_outcome(s, problem, outcome, kind="REOPTIMIZED", created_by=actor,
                          parent_version_id=version.id, params=params)
    new.notes = reason
    s.commit()
    return {"version": version_dict(new), "diff": _diff_json(s, outcome.diff) if outcome.diff else None,
            "lock_conflicts": [{"employee_id": c.employee_id, "date": c.date.isoformat(), "reason": c.reason}
                               for c in outcome.solve.lock_conflicts]}


def _diff_json(s: Session, diff) -> dict:
    lk = Lookups(s)
    name = lambda e: lk.employees[e].name if e in lk.employees else str(e)  # noqa: E731
    shift = lambda x: lk.shifts[x].code if x in lk.shifts else None  # noqa: E731
    return {
        "changed_entries": [{"employee_id": b.employee_id, "employee": name(b.employee_id), "date": b.date.isoformat(),
                             "before": {"status": b.status.value, "shift": shift(b.shift_id)},
                             "after": {"status": a.status.value, "shift": shift(a.shift_id)}}
                            for b, a in diff.changed_entries],
        "added_duties": [{"employee_id": d.employee_id, "employee": name(d.employee_id), "date": d.date.isoformat(),
                          "duty_type": d.duty_type.value, **lk.slot_info(d.slot_id)} for d in diff.added_duties],
        "removed_duties": [{"employee_id": d.employee_id, "employee": name(d.employee_id), "date": d.date.isoformat(),
                            "duty_type": d.duty_type.value, **lk.slot_info(d.slot_id)} for d in diff.removed_duties],
    }


def diff_versions(s: Session, a: m.RosterVersion, b: m.RosterVersion) -> dict:
    if a.plan_id != b.plan_id:
        raise DomainError("Versions belong to different months.")
    return _diff_json(s, diff_rosters(load_roster(s, a.id), load_roster(s, b.id)))


# ───────────────────────────── views ─────────────────────────────
VIEWS = ("company", "pod", "brand", "process", "employee")


def roster_view(s: Session, version: m.RosterVersion, view: str, ref_id: int | None) -> dict:
    if view not in VIEWS:
        raise DomainError(f"view must be one of {', '.join(VIEWS)}")
    if view != "company" and ref_id is None:
        raise DomainError(f"ref_id is required for the {view} view")
    ensure_fresh(s, version)
    lk = Lookups(s)
    first, last = month_bounds(version.plan.year, version.plan.month)
    days = month_days(version.plan.year, version.plan.month)
    assignments = s.scalars(select(m.Assignment).where(
        m.Assignment.effective_from <= last,
        (m.Assignment.effective_to.is_(None)) | (m.Assignment.effective_to >= first))).all()

    if view == "company":
        emp_ids, slot_ids = set(lk.employees), set(lk.slots)
    elif view == "pod":
        if ref_id not in lk.pods:
            raise NotFound("Pod not found")
        emp_ids = {e.id for e in lk.employees.values() if e.pod_id == ref_id}
        bps = {a.brand_process_id for a in assignments if a.employee_id in emp_ids and a.role == "PRIMARY"}
        slot_ids = {x.id for x in lk.slots.values() if x.brand_process_id in bps}
    elif view == "brand":
        if ref_id not in lk.brands:
            raise NotFound("Brand not found")
        bps = {b.id for b in lk.bps.values() if b.brand_id == ref_id}
        emp_ids = {a.employee_id for a in assignments if a.brand_process_id in bps}
        slot_ids = {x.id for x in lk.slots.values() if x.brand_process_id in bps}
    elif view == "process":
        if ref_id not in lk.processes:
            raise NotFound("Process not found")
        bps = {b.id for b in lk.bps.values() if b.process_id == ref_id}
        emp_ids = {a.employee_id for a in assignments if a.brand_process_id in bps}
        slot_ids = {x.id for x in lk.slots.values() if x.brand_process_id in bps}
    else:
        if ref_id not in lk.employees:
            raise NotFound("Employee not found")
        emp_ids = {ref_id}
        bps = {a.brand_process_id for a in assignments if a.employee_id == ref_id}
        slot_ids = {x.id for x in lk.slots.values() if x.brand_process_id in bps}

    entries = s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == version.id,
                                                    m.RosterEntry.employee_id.in_(emp_ids))).all()
    duties = s.scalars(select(m.RosterDuty).where(m.RosterDuty.version_id == version.id,
                                                  m.RosterDuty.employee_id.in_(emp_ids))).all()
    duty_map: dict[tuple[int, date], list] = defaultdict(list)
    for d in duties:
        info = lk.slot_info(d.brand_process_shift_id)
        duty_map[(d.employee_id, d.date)].append({"duty_id": d.id, "slot_id": d.brand_process_shift_id,
                                                  "label": info["label"], "brand": info["brand"],
                                                  "process": info["process"], "duty_type": d.duty_type,
                                                  "source": d.source})
    cells: dict[int, dict[date, dict]] = defaultdict(dict)
    for e in entries:
        cells[e.employee_id][e.date] = {"entry_id": e.id, "date": e.date.isoformat(), "status": e.status,
                                        "shift": lk.shifts[e.shift_id].code if e.shift_id else None,
                                        "shift_id": e.shift_id, "source": e.source, "locked": e.is_locked,
                                        "duties": duty_map.get((e.employee_id, e.date), [])}
    rows = []
    for eid in sorted(emp_ids, key=lambda i: (lk.employees[i].pod_id, lk.employees[i].name)):
        if eid not in cells:
            continue
        emp = lk.employees[eid]
        row_cells = [cells[eid].get(d) for d in days]
        counts = defaultdict(int)
        for c in row_cells:
            if c:
                counts[c["status"]] += 1
                counts["BACKUP_DUTIES"] += sum(1 for x in c["duties"] if x["duty_type"] == "BACKUP")
        rows.append({"employee_id": eid, "code": emp.code, "name": emp.name, "pod_id": emp.pod_id,
                     "pod": lk.pods[emp.pod_id].name, "is_lead": lk.pods[emp.pod_id].lead_employee_id == eid,
                     "cells": row_cells, "totals": dict(counts)})

    cov_rows = s.scalars(select(m.RosterCoverage).where(m.RosterCoverage.version_id == version.id,
                                                        m.RosterCoverage.brand_process_shift_id.in_(slot_ids))).all()
    cov: dict[int, dict[date, m.RosterCoverage]] = defaultdict(dict)
    for c in cov_rows:
        cov[c.brand_process_shift_id][c.date] = c
    coverage = []
    for sid in sorted(cov, key=lambda x: lk.slot_info(x)["label"]):
        info = lk.slot_info(sid)
        coverage.append({**info, "cells": [
            {"date": d.isoformat(), "required": cov[sid][d].required, "staffed": cov[sid][d].staffed,
             "backup_count": cov[sid][d].backup_count, "status": cov[sid][d].status}
            if d in cov[sid] else None for d in days]})
    return {"version": version_dict(version), "view": view, "ref_id": ref_id,
            "days": [d.isoformat() for d in days], "employees": rows, "coverage": coverage}


def day_view(s: Session, version: m.RosterVersion, d: date) -> dict:
    """Who is working on a date, on which duties, and what is uncovered."""
    ensure_fresh(s, version)
    lk = Lookups(s)
    entries = s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == version.id,
                                                    m.RosterEntry.date == d)).all()
    if not entries:
        raise NotFound("Date is outside this version's month")
    duties = defaultdict(list)
    for x in s.scalars(select(m.RosterDuty).where(m.RosterDuty.version_id == version.id, m.RosterDuty.date == d)):
        duties[x.employee_id].append({"label": lk.slot_info(x.brand_process_shift_id)["label"],
                                      "duty_type": x.duty_type})
    working, off = [], defaultdict(list)
    for e in sorted(entries, key=lambda e: lk.employees[e.employee_id].name):
        emp = lk.employees[e.employee_id]
        item = {"employee_id": emp.id, "name": emp.name, "pod": lk.pods[emp.pod_id].name}
        if e.status == "WORK":
            working.append({**item, "shift": lk.shifts[e.shift_id].code, "duties": duties[emp.id]})
        else:
            off[e.status].append(item)
    gaps = [{**lk.slot_info(c.brand_process_shift_id), "required": c.required, "staffed": c.staffed,
             "status": c.status}
            for c in s.scalars(select(m.RosterCoverage).where(
                m.RosterCoverage.version_id == version.id, m.RosterCoverage.date == d,
                m.RosterCoverage.status.in_(("UNDERSTAFFED", "UNCOVERED"))))]
    return {"date": d.isoformat(), "working": working, "off": off, "gaps": gaps}


def export_csv(s: Session, version: m.RosterVersion) -> str:
    lk = Lookups(s)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["employee_code", "employee", "pod", "date", "status", "shift", "duties"])
    duties = defaultdict(list)
    for x in s.scalars(select(m.RosterDuty).where(m.RosterDuty.version_id == version.id)):
        duties[x.entry_id].append(f"{lk.slot_info(x.brand_process_shift_id)['label']}"
                                  f"{' (backup)' if x.duty_type == 'BACKUP' else ''}")
    for e in s.scalars(select(m.RosterEntry).where(m.RosterEntry.version_id == version.id)
                       .order_by(m.RosterEntry.employee_id, m.RosterEntry.date)):
        emp = lk.employees[e.employee_id]
        w.writerow([emp.code, emp.name, lk.pods[emp.pod_id].name, e.date.isoformat(), e.status,
                    lk.shifts[e.shift_id].code if e.shift_id else "", "; ".join(sorted(duties[e.id]))])
    return buf.getvalue()


# ───────────────────────────── change impact ─────────────────────────────
def current_version(s: Session, year: int, month: int) -> m.RosterVersion | None:
    """Published version if any, else the newest live draft with a roster."""
    q = select(m.RosterVersion).join(m.RosterPlan).where(m.RosterPlan.year == year, m.RosterPlan.month == month)
    pub = s.scalar(q.where(m.RosterVersion.status == "PUBLISHED"))
    if pub is not None:
        return pub
    return s.scalar(q.where(m.RosterVersion.status == "DRAFT", m.RosterVersion.validation_status.not_in(NO_ROSTER))
                    .order_by(m.RosterVersion.version_no.desc()))


def impact_preview(s: Session, employee_id: int, date_from: date, date_to: date) -> dict:
    """What would break if this employee became unavailable on these dates? (read-only)"""
    emp = s.get(m.Employee, employee_id)
    if emp is None:
        raise NotFound("Employee not found")
    lk = Lookups(s)
    months, y, mo = [], date_from.year, date_from.month
    while (y, mo) <= (date_to.year, date_to.month):
        months.append((y, mo))
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    results = []
    for y, mo in months:
        v = current_version(s, y, mo)
        if v is None:
            results.append({"year": y, "month": mo, "version_id": None, "message": "No roster exists for this month."})
            continue
        problem = load_problem(s, y, mo)
        roster = load_roster(s, v.id)
        before = validate(problem, roster)
        problem.absences.append(t.Absence(employee_id, date_from, date_to, t.AbsenceKind.UNAVAILABLE, "what-if"))
        sim = t.Roster(
            [t.RosterEntry(e.employee_id, e.date, t.EntryStatus.UNAVAILABLE)
             if e.employee_id == employee_id and date_from <= e.date <= date_to else e for e in roster.entries],
            [d for d in roster.duties if not (d.employee_id == employee_id and date_from <= d.date <= date_to)],
        )
        after = validate(problem, sim)
        old_gaps = {(c.slot_id, c.date): c for c in before.gaps}
        new_gaps = []
        for c in after.gaps:
            prev = old_gaps.get((c.slot_id, c.date))
            if prev is None or c.staffed < prev.staffed:
                new_gaps.append({**lk.slot_info(c.slot_id), "date": c.date.isoformat(), "required": c.required,
                                 "staffed": c.staffed, "status": c.status.value,
                                 "suggestions": [
                                     {"employee_id": x.employee_id, "name": x.name, "action": x.action,
                                      "role": x.role, "reasons": list(x.reasons), "impact": list(x.impact)}
                                     for x in suggest(problem, sim, c.slot_id, c.date, 3)]})
        lost = sorted({lk.slot_info(d.slot_id)["brand"] for d in roster.duties
                       if d.employee_id == employee_id and date_from <= d.date <= date_to})
        results.append({"year": y, "month": mo, "version_id": v.id, "version_no": v.version_no,
                        "version_status": v.status, "brands_affected": lost,
                        "duties_lost": sum(1 for d in roster.duties
                                           if d.employee_id == employee_id and date_from <= d.date <= date_to),
                        "new_gaps": new_gaps,
                        "coverage_pct_before": before.coverage_pct, "coverage_pct_after": after.coverage_pct})
    return {"employee_id": employee_id, "employee": emp.name, "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(), "months": results}
