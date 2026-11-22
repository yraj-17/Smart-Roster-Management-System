from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.orm import Session

from app import models as m


def row_dict(obj, exclude: tuple[str, ...] = ("created_at", "updated_at")) -> dict | None:
    if obj is None:
        return None
    out = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        v = getattr(obj, col.name)
        if isinstance(v, (date, datetime, time)):
            v = v.isoformat()
        elif isinstance(v, Decimal):
            v = float(v)
        out[col.name] = v
    return out


def log(s: Session, actor: str, entity_type: str, entity_id: int | None, action: str,
        before: dict | None = None, after: dict | None = None, reason: str | None = None,
        version_id: int | None = None) -> None:
    s.add(m.AuditLog(actor=actor, entity_type=entity_type, entity_id=entity_id, action=action,
                     before=before, after=after, reason=reason, version_id=version_id))
