"""Mark roster versions STALE when their inputs change.

Only live versions (DRAFT or PUBLISHED) that hold a roster are affected; INFEASIBLE
and SOLVER_TIMEOUT versions are historical records without entries.  A STALE
version is re-validated on its next read or action (see validation_service).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app import models as m

LIVE = ("DRAFT", "PUBLISHED")
NO_ROSTER = ("INFEASIBLE", "SOLVER_TIMEOUT")


def mark_stale(s: Session, date_from: date | None = None, date_to: date | None = None) -> list[int]:
    """Mark live versions stale; limit to months overlapping [date_from, date_to] if given."""
    q = select(m.RosterVersion.id).join(m.RosterPlan).where(
        m.RosterVersion.status.in_(LIVE), m.RosterVersion.validation_status.not_in(NO_ROSTER))
    if date_from is not None and date_to is not None:
        months = []
        y, mo = date_from.year, date_from.month
        while (y, mo) <= (date_to.year, date_to.month):
            months.append(and_(m.RosterPlan.year == y, m.RosterPlan.month == mo))
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        q = q.where(or_(*months))
    ids = list(s.scalars(q))
    if ids:
        s.execute(update(m.RosterVersion).where(m.RosterVersion.id.in_(ids)).values(validation_status="STALE"))
    return ids
