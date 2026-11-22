"""Leaves, unavailability and the comp-off ledger."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, enum_check

LEAVE_TYPES = ["PLANNED", "SICK", "CASUAL", "OTHER"]
REQUEST_STATUSES = ["REQUESTED", "APPROVED", "REJECTED", "CANCELLED"]
CREDIT_SOURCES = ["HOLIDAY_WORK", "REST_DAY_WORK", "MANUAL"]
CREDIT_STATUSES = ["PENDING", "AVAILABLE", "REJECTED", "CONSUMED", "EXPIRED", "REVERSED"]


class Leave(IdMixin, TimestampMixin, Base):
    __tablename__ = "leaves"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="date_order"),
        enum_check("leave_type", LEAVE_TYPES),
        enum_check("status", REQUEST_STATUSES),
        Index("ix_leaves_employee_dates", "employee_id", "start_date", "end_date"),
        Index("ix_leaves_status", "status"),
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    leave_type: Mapped[str] = mapped_column(String(16), default="PLANNED")
    status: Mapped[str] = mapped_column(String(12), default="REQUESTED")
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    employee: Mapped["Employee"] = relationship()  # noqa: F821


class Unavailability(IdMixin, TimestampMixin, Base):
    __tablename__ = "unavailability"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="date_order"),
        Index("ix_unavailability_employee_dates", "employee_id", "start_date", "end_date"),
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(200))
    employee: Mapped["Employee"] = relationship()  # noqa: F821


class CompOffCredit(IdMixin, TimestampMixin, Base):
    """Lifecycle: PENDING -> AVAILABLE (approved, with expiry) -> CONSUMED | EXPIRED;
    REJECTED by the manager; REVERSED when a later published version removes the
    work that earned it.  Every transition is written to audit_log."""
    __tablename__ = "comp_off_credits"
    __table_args__ = (
        enum_check("source", CREDIT_SOURCES),
        enum_check("status", CREDIT_STATUSES),
        UniqueConstraint("employee_id", "earned_on", "source"),
        Index("ix_comp_off_credits_employee_status", "employee_id", "status"),
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"))
    earned_on: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))
    source_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("roster_versions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="PENDING")
    expires_on: Mapped[date | None] = mapped_column(Date)
    consumed_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    employee: Mapped["Employee"] = relationship()  # noqa: F821


class CompOffRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "comp_off_requests"
    __table_args__ = (
        enum_check("status", REQUEST_STATUSES),
        Index("uq_comp_off_requests_active_credit", "credit_id", unique=True,
              postgresql_where=text("status IN ('REQUESTED','APPROVED')")),
        Index("ix_comp_off_requests_employee_date", "employee_id", "date"),
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    credit_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("comp_off_credits.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(10), default="REQUESTED")
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credit: Mapped[CompOffCredit] = relationship()
