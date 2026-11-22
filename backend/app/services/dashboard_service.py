from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m

from .engine_adapter import month_bounds
from .roster_service import Lookups, current_version, version_dict
from .validation_service import ensure_fresh


def summary(s: Session, year: int, month: int, today: date | None = None) -> dict:
    today = today or date.today()
    first, last = month_bounds(year, month)
    lk = Lookups(s)

    primaries: dict[int, set[int]] = defaultdict(set)
    for a in s.scalars(select(m.Assignment).where(m.Assignment.role == "PRIMARY", m.Assignment.effective_from <= last,
                                                  (m.Assignment.effective_to.is_(None))
                                                  | (m.Assignment.effective_to >= first))):
        primaries[lk.bps[a.brand_process_id].brand_id].add(a.employee_id)
    active_brands = [b for b in lk.brands.values() if b.active]
    counts = {
        "employees": sum(e.active for e in lk.employees.values()),
        "brands": len(active_brands),
        "processes": sum(p.active for p in lk.processes.values()),
        "pods": sum(p.active for p in lk.pods.values()),
        "brand_processes": sum(b.active for b in lk.bps.values()),
        "single_resource_brands": sum(1 for b in active_brands if len(primaries.get(b.id, ())) == 1),
        "multi_resource_brands": sum(1 for b in active_brands if len(primaries.get(b.id, ())) > 1),
    }

    versions = s.scalars(select(m.RosterVersion).join(m.RosterPlan).where(
        m.RosterPlan.year == year, m.RosterPlan.month == month).order_by(m.RosterVersion.version_no)).all()
    cur = current_version(s, year, month)
    roster = None
    if cur is not None:
        ensure_fresh(s, cur)
        conflicts = s.scalars(select(m.RosterConflict).where(m.RosterConflict.version_id == cur.id,
                                                             m.RosterConflict.status != "RESOLVED")).all()
        by_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"OPEN": 0, "ACKNOWLEDGED": 0})
        for c in conflicts:
            by_cat[c.category][c.status] += 1
        cov = s.scalars(select(m.RosterCoverage).where(m.RosterCoverage.version_id == cur.id)).all()
        per_day: dict[date, list[int]] = defaultdict(lambda: [0, 0])
        brand_gaps: dict[int, int] = defaultdict(int)
        for c in cov:
            if c.required > 0:
                per_day[c.date][0] += min(c.staffed, c.required)
                per_day[c.date][1] += c.required
            if c.status in ("UNDERSTAFFED", "UNCOVERED"):
                brand_gaps[lk.slot_info(c.brand_process_shift_id)["brand_id"]] += 1
        entries = s.execute(select(m.RosterEntry.status, func.count()).where(m.RosterEntry.version_id == cur.id)
                            .group_by(m.RosterEntry.status)).all()
        backup_duties = s.scalar(select(func.count()).select_from(m.RosterDuty).where(
            m.RosterDuty.version_id == cur.id, m.RosterDuty.duty_type == "BACKUP"))
        today_snapshot = None
        if first <= today <= last:
            rows = s.execute(select(m.RosterEntry.status, func.count()).where(
                m.RosterEntry.version_id == cur.id, m.RosterEntry.date == today).group_by(m.RosterEntry.status)).all()
            today_snapshot = {"date": today.isoformat(), **{st: n for st, n in rows}}
        roster = {
            "version": version_dict(cur),
            "conflicts": {k: dict(v) for k, v in by_cat.items()},
            "open_hard": sum(1 for c in conflicts if c.status == "OPEN" and c.severity == "HARD"),
            "open_soft": sum(1 for c in conflicts if c.status == "OPEN" and c.severity == "SOFT"),
            "daily_coverage": [{"date": d.isoformat(), "pct": round(100 * a / b, 2) if b else 100.0,
                                "staffed": a, "required": b} for d, (a, b) in sorted(per_day.items())],
            "brands_at_risk": [{"brand_id": b, "brand": lk.brands[b].name, "gap_slot_days": n}
                               for b, n in sorted(brand_gaps.items(), key=lambda x: -x[1])[:6]],
            "entry_status_counts": {st: n for st, n in entries},
            "backup_duties": backup_duties,
            "today": today_snapshot,
        }

    horizon_end = max(last, today + timedelta(days=14))
    horizon_start = min(first, today)
    leaves = s.scalars(select(m.Leave).where(m.Leave.status.in_(("APPROVED", "REQUESTED")),
                                             m.Leave.end_date >= max(horizon_start, today),
                                             m.Leave.start_date <= horizon_end)
                       .order_by(m.Leave.start_date)).all()
    pending_credits = s.scalar(select(func.count()).select_from(m.CompOffCredit)
                               .where(m.CompOffCredit.status == "PENDING"))
    return {
        "year": year, "month": month, "counts": counts,
        "versions": [{"id": v.id, "version_no": v.version_no, "status": v.status, "kind": v.kind,
                      "validation_status": v.validation_status,
                      "coverage_pct": float(v.coverage_pct) if v.coverage_pct is not None else None}
                     for v in versions],
        "current": roster,
        "upcoming_leaves": [{"id": lv.id, "employee_id": lv.employee_id, "employee": lk.employees[lv.employee_id].name,
                             "start_date": lv.start_date.isoformat(), "end_date": lv.end_date.isoformat(),
                             "status": lv.status, "leave_type": lv.leave_type} for lv in leaves],
        "pending_leave_requests": sum(1 for lv in leaves if lv.status == "REQUESTED"),
        "pending_comp_off_credits": pending_credits,
    }
