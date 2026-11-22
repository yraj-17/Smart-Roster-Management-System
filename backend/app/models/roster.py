"""Roster plans, versions, entries, duties, coverage, conflicts and the audit log.

Integrity guarantees enforced by PostgreSQL itself
--------------------------------------------------
* roster_duties -> roster_entries composite FK on
  (entry_id, version_id, employee_id, date, shift_id, entry_status) with
  entry_status CHECKed to 'WORK': a duty can only reference a WORK entry with the
  same version/employee/date/shift.  Changing a referenced entry to any non-WORK
  status (or another shift) is rejected (ON UPDATE RESTRICT) until its duties are
  removed in the same transaction.
* roster_duties -> brand_process_shifts composite FK on
  (brand_process_shift_id, brand_process_id, shift_id): the duty's shift is a
  shift its slot actually runs.
* roster_duties -> assignments composite FK on
  (assignment_id, employee_id, brand_process_id, duty_type): the authorising
  assignment belongs to the same employee and brand-process and duty_type = role.
* UNIQUE (version_id, employee_id, date, brand_process_id): no double counting.
* Date/shift eligibility is checked by trigger trg_roster_duty_eligibility.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, enum_check

ENTRY_STATUSES = ["WORK", "WEEKLY_OFF", "LEAVE", "COMP_OFF", "HOLIDAY", "UNAVAILABLE"]
SOURCES = ["AUTO", "MANUAL", "REOPT"]
VERSION_KINDS = ["GENERATED", "REOPTIMIZED", "MANUAL_CLONE"]
VERSION_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED", "ARCHIVED"]
VALIDATION_STATUSES = ["FULLY_COVERED", "PARTIALLY_COVERED", "INVALID", "INFEASIBLE",
                       "SOLVER_TIMEOUT", "STALE"]
SLOT_STATUSES = ["MET", "UNDERSTAFFED", "UNCOVERED", "NOT_REQUIRED"]


class RosterPlan(IdMixin, TimestampMixin, Base):
    __tablename__ = "roster_plans"
    __table_args__ = (
        UniqueConstraint("year", "month"),
        CheckConstraint("month BETWEEN 1 AND 12", name="month_range"),
    )
    year: Mapped[int] = mapped_column(SmallInteger)
    month: Mapped[int] = mapped_column(SmallInteger)
    versions: Mapped[list[RosterVersion]] = relationship(back_populates="plan", cascade="all, delete-orphan",
                                                         order_by="RosterVersion.version_no")


class RosterVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "roster_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "version_no"),
        Index("uq_roster_versions_one_published", "plan_id", unique=True,
              postgresql_where=text("status = 'PUBLISHED'")),
        enum_check("kind", VERSION_KINDS),
        enum_check("status", VERSION_STATUSES),
        enum_check("validation_status", VALIDATION_STATUSES),
    )
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roster_plans.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("roster_versions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(12), default="DRAFT")
    validation_status: Mapped[str] = mapped_column(String(20))
    coverage_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    params: Mapped[dict | None] = mapped_column(JSONB)
    solver_stats: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(80))
    published_by: Mapped[str | None] = mapped_column(String(80))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped[RosterPlan] = relationship(back_populates="versions")


class RosterEntry(IdMixin, TimestampMixin, Base):
    """One row per employee per day: working (with its single shift) or why not."""
    __tablename__ = "roster_entries"
    __table_args__ = (
        enum_check("status", ENTRY_STATUSES),
        enum_check("source", SOURCES),
        CheckConstraint("(status = 'WORK') = (shift_id IS NOT NULL)", name="shift_iff_work"),
        UniqueConstraint("version_id", "employee_id", "date"),
        UniqueConstraint("id", "version_id", "employee_id", "date", "shift_id", "status",
                         name="uq_roster_entries_duty_target"),
        Index("ix_roster_entries_version_date", "version_id", "date"),
    )
    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roster_versions.id", ondelete="CASCADE"))
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="RESTRICT"))
    date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12))
    shift_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shifts.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(8), default="AUTO")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    note: Mapped[str | None] = mapped_column(String(200))


class RosterDuty(IdMixin, TimestampMixin, Base):
    """What an employee actually does on a WORK day: one row per brand-process."""
    __tablename__ = "roster_duties"
    __table_args__ = (
        CheckConstraint("entry_status = 'WORK'", name="entry_must_be_work"),
        enum_check("duty_type", ["PRIMARY", "BACKUP"]),
        enum_check("source", SOURCES),
        ForeignKeyConstraint(
            ["entry_id", "version_id", "employee_id", "date", "shift_id", "entry_status"],
            ["roster_entries.id", "roster_entries.version_id", "roster_entries.employee_id",
             "roster_entries.date", "roster_entries.shift_id", "roster_entries.status"],
            ondelete="CASCADE", onupdate="RESTRICT", name="fk_roster_duties_entry",
        ),
        ForeignKeyConstraint(
            ["brand_process_shift_id", "brand_process_id", "shift_id"],
            ["brand_process_shifts.id", "brand_process_shifts.brand_process_id", "brand_process_shifts.shift_id"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_roster_duties_slot",
        ),
        ForeignKeyConstraint(
            ["assignment_id", "employee_id", "brand_process_id", "duty_type"],
            ["assignments.id", "assignments.employee_id", "assignments.brand_process_id", "assignments.role"],
            ondelete="RESTRICT", onupdate="RESTRICT", name="fk_roster_duties_assignment",
        ),
        UniqueConstraint("version_id", "employee_id", "date", "brand_process_id",
                         name="uq_roster_duties_no_double_count"),
        Index("ix_roster_duties_coverage", "version_id", "date", "brand_process_shift_id"),
        Index("ix_roster_duties_employee_day", "version_id", "employee_id", "date"),
    )
    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roster_versions.id", ondelete="CASCADE"))
    entry_id: Mapped[int] = mapped_column(BigInteger)
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="RESTRICT"))
    date: Mapped[date] = mapped_column(Date)
    shift_id: Mapped[int] = mapped_column(BigInteger)
    entry_status: Mapped[str] = mapped_column(String(12), default="WORK", server_default="WORK")
    brand_process_shift_id: Mapped[int] = mapped_column(BigInteger)
    brand_process_id: Mapped[int] = mapped_column(BigInteger)
    assignment_id: Mapped[int] = mapped_column(BigInteger)
    duty_type: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(8), default="AUTO")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class RosterCoverage(IdMixin, Base):
    """Validator output per slot-day, materialised for fast views."""
    __tablename__ = "roster_coverage"
    __table_args__ = (
        UniqueConstraint("version_id", "brand_process_shift_id", "date"),
        enum_check("status", SLOT_STATUSES),
        Index("ix_roster_coverage_version_status", "version_id", "status"),
    )
    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roster_versions.id", ondelete="CASCADE"))
    brand_process_shift_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("brand_process_shifts.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    required: Mapped[int] = mapped_column(SmallInteger)
    staffed: Mapped[int] = mapped_column(SmallInteger)
    primary_count: Mapped[int] = mapped_column(SmallInteger)
    backup_count: Mapped[int] = mapped_column(SmallInteger)
    backup_capacity: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(14))


class RosterConflict(IdMixin, TimestampMixin, Base):
    __tablename__ = "roster_conflicts"
    __table_args__ = (
        enum_check("severity", ["HARD", "SOFT"]),
        enum_check("category", ["INTEGRITY", "EMPLOYEE_RULE", "COVERAGE", "PREFERENCE", "CONFIG", "SOLVER"]),
        enum_check("status", ["OPEN", "RESOLVED", "ACKNOWLEDGED"]),
        Index("ix_roster_conflicts_version_status", "version_id", "status", "severity"),
        Index("ix_roster_conflicts_version_date", "version_id", "date"),
    )
    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("roster_versions.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(4))
    date: Mapped[date | None] = mapped_column(Date)
    employee_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="SET NULL"))
    brand_process_shift_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("brand_process_shifts.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    explanation: Mapped[dict | None] = mapped_column(JSONB)
    suggestions: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12), default="OPEN")
    ack_reason: Mapped[str | None] = mapped_column(Text)
    ack_by: Mapped[str | None] = mapped_column(String(80))
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_version_created", "version_id", "created_at"),
    )
    actor: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("roster_versions.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
