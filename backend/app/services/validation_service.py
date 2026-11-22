"""Persisting validator results and keeping versions fresh.

Conflict rows are *synchronised*, not recreated: an issue is identified by
(type, date, employee, slot).  Still-present issues keep their row id and
acknowledgement, vanished issues become RESOLVED, reappearing ones re-open.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models as m
from app.scheduling import suggest, validate
from app.scheduling import types as t
from app.scheduling.validator import ValidationReport

from .engine_adapter import load_problem, load_roster

NO_ROSTER = ("INFEASIBLE", "SOLVER_TIMEOUT")


def summary_of(rep: ValidationReport) -> dict:
    return {
        "gaps": len(rep.gaps),
        "uncovered": sum(c.status == t.SlotStatus.UNCOVERED for c in rep.gaps),
        "understaffed": sum(c.status == t.SlotStatus.UNDERSTAFFED for c in rep.gaps),
        "hard_rule_violations": rep.hard_rule_violations,
        "soft_issues": sum(i.severity == t.Severity.SOFT for i in rep.issues),
        "required_slot_days": sum(1 for c in rep.coverage if c.required > 0),
    }


def suggestion_json(x) -> dict:
    return {"employee_id": x.employee_id, "name": x.name, "action": x.action, "assignment_id": x.assignment_id,
            "role": x.role, "score": x.score, "reasons": list(x.reasons), "impact": list(x.impact),
            "swap_off_date": x.swap_off_date.isoformat() if x.swap_off_date else None}


def _key(type_, d, emp, slot):
    return (type_, d, emp, slot)


def store_report(s: Session, version: m.RosterVersion, problem: t.Problem, roster: t.Roster,
                 rep: ValidationReport, max_suggestions: int = 3) -> None:
    """Write coverage, sync conflicts and update the version's status fields."""
    s.execute(delete(m.RosterCoverage).where(m.RosterCoverage.version_id == version.id))
    s.add_all([
        m.RosterCoverage(version_id=version.id, brand_process_shift_id=c.slot_id, date=c.date,
                         required=c.required, staffed=c.staffed, primary_count=c.primary_count,
                         backup_count=c.backup_count, backup_capacity=c.backup_capacity, status=c.status.value)
        for c in rep.coverage
    ])
    existing = {
        _key(c.type, c.date, c.employee_id, c.brand_process_shift_id): c
        for c in s.scalars(select(m.RosterConflict).where(m.RosterConflict.version_id == version.id,
                                                          m.RosterConflict.category != "SOLVER"))
    }
    seen = set()
    for i in rep.issues:
        k = _key(i.type, i.date, i.employee_id, i.slot_id)
        if k in seen:
            continue
        seen.add(k)
        sugg = None
        if i.category == t.Category.COVERAGE and i.slot_id and i.date:
            sugg = [suggestion_json(x) for x in suggest(problem, roster, i.slot_id, i.date, max_suggestions)]
        row = existing.get(k)
        if row is None:
            s.add(m.RosterConflict(version_id=version.id, type=i.type, category=i.category.value,
                                   severity=i.severity.value, date=i.date, employee_id=i.employee_id,
                                   brand_process_shift_id=i.slot_id, message=i.message,
                                   explanation=i.details or None, suggestions=sugg, status="OPEN"))
        else:
            row.message, row.explanation, row.suggestions = i.message, i.details or None, sugg
            row.category, row.severity = i.category.value, i.severity.value
            if row.status == "RESOLVED":
                row.status, row.ack_reason, row.ack_by, row.ack_at = "OPEN", None, None, None
    for k, row in existing.items():
        if k not in seen and row.status != "RESOLVED":
            row.status = "RESOLVED"
    version.validation_status = rep.status.value
    version.coverage_pct = Decimal(str(rep.coverage_pct))
    version.summary = summary_of(rep)
    s.flush()


def revalidate(s: Session, version: m.RosterVersion) -> ValidationReport | None:
    """Re-run the independent validator against current master data."""
    if version.validation_status in NO_ROSTER:
        return None
    problem = load_problem(s, version.plan.year, version.plan.month)
    roster = load_roster(s, version.id)
    rep = validate(problem, roster)
    store_report(s, version, problem, roster, rep)
    return rep


def ensure_fresh(s: Session, version: m.RosterVersion) -> None:
    if version.validation_status == "STALE":
        revalidate(s, version)
        s.commit()
