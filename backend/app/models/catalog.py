"""Brands, processes, shifts, coverage slots, requirements and assignments."""
from __future__ import annotations

from datetime import date, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, enum_check


class Process(IdMixin, TimestampMixin, Base):
    __tablename__ = "processes"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Brand(IdMixin, TimestampMixin, Base):
    """One holiday calendar per brand, shared by all of its processes."""
    __tablename__ = "brands"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    holiday_calendar_id: Mapped[int | None] = mapped_column(
        ForeignKey("holiday_calendars.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    processes: Mapped[list[BrandProcess]] = relationship(back_populates="brand",
                                                         cascade="all, delete-orphan")


class Shift(IdMixin, TimestampMixin, Base):
    """end_time < start_time means the shift crosses midnight."""
    __tablename__ = "shifts"
    __table_args__ = (CheckConstraint("start_time <> end_time", name="non_zero_length"),)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class BrandProcess(IdMixin, TimestampMixin, Base):
    """A brand's process and its operating calendar (bit0 = Monday)."""
    __tablename__ = "brand_processes"
    __table_args__ = (
        UniqueConstraint("brand_id", "process_id"),
        CheckConstraint("operating_days_mask BETWEEN 0 AND 127", name="mask_range"),
    )
    brand_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("brands.id", ondelete="CASCADE"))
    process_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("processes.id", ondelete="RESTRICT"))
    operating_days_mask: Mapped[int] = mapped_column(SmallInteger, default=127, server_default="127")
    operates_on_holidays: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    brand: Mapped[Brand] = relationship(back_populates="processes")
    process: Mapped[Process] = relationship()
    slots: Mapped[list[BrandProcessShift]] = relationship(back_populates="brand_process",
                                                          cascade="all, delete-orphan")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="brand_process",
                                                         cascade="all, delete-orphan")


class BrandProcessShift(IdMixin, TimestampMixin, Base):
    """Coverage slot definition: a shift a process runs and its default minimum headcount."""
    __tablename__ = "brand_process_shifts"
    __table_args__ = (
        UniqueConstraint("brand_process_id", "shift_id"),
        UniqueConstraint("id", "brand_process_id", "shift_id", name="uq_bps_id_bp_shift"),
        CheckConstraint("default_min_staff >= 0", name="min_staff_non_negative"),
    )
    brand_process_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("brand_processes.id", ondelete="CASCADE"))
    shift_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shifts.id", ondelete="RESTRICT"))
    default_min_staff: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    brand_process: Mapped[BrandProcess] = relationship(back_populates="slots")
    shift: Mapped[Shift] = relationship()
    requirements: Mapped[list[CoverageRequirement]] = relationship(back_populates="slot",
                                                                   cascade="all, delete-orphan")


class CoverageRequirement(IdMixin, TimestampMixin, Base):
    """Per-slot override of minimum headcount for a weekday or a specific date."""
    __tablename__ = "coverage_requirements"
    __table_args__ = (
        CheckConstraint("(day_of_week IS NULL) <> (specific_date IS NULL)", name="exactly_one_target"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="dow_range"),
        CheckConstraint("min_staff >= 0", name="min_staff_non_negative"),
        UniqueConstraint("brand_process_shift_id", "day_of_week", name="uq_cov_req_slot_dow"),
        UniqueConstraint("brand_process_shift_id", "specific_date", name="uq_cov_req_slot_date"),
    )
    brand_process_shift_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("brand_process_shifts.id", ondelete="CASCADE"))
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger)
    specific_date: Mapped[date | None] = mapped_column(Date)
    min_staff: Mapped[int] = mapped_column(SmallInteger)
    reason: Mapped[str | None] = mapped_column(String(200))
    slot: Mapped[BrandProcessShift] = relationship(back_populates="requirements")


class Assignment(IdMixin, TimestampMixin, Base):
    """Eligibility/responsibility of an employee for a brand-process.

    At any date an employee holds at most one assignment per brand-process (either
    PRIMARY or BACKUP) - enforced by a GiST exclusion constraint on date ranges.
    """
    __tablename__ = "assignments"
    __table_args__ = (
        enum_check("role", ["PRIMARY", "BACKUP"]),
        CheckConstraint("load_pct BETWEEN 1 AND 100", name="load_range"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="date_order"),
        UniqueConstraint("id", "employee_id", "brand_process_id", "role", name="uq_assignments_identity"),
        ExcludeConstraint(
            ("employee_id", "="),
            ("brand_process_id", "="),
            (text("daterange(effective_from, effective_to, '[]')"), "&&"),
            name="ex_assignments_no_overlap",
            using="gist",
        ),
        Index("ix_assignments_bp_role", "brand_process_id", "role"),
        Index("ix_assignments_employee", "employee_id"),
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"))
    brand_process_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("brand_processes.id", ondelete="CASCADE"))
    shift_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shifts.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(String(8))
    load_pct: Mapped[int] = mapped_column(SmallInteger)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)

    employee: Mapped["Employee"] = relationship()  # noqa: F821
    brand_process: Mapped[BrandProcess] = relationship(back_populates="assignments")
    shift: Mapped[Shift | None] = relationship()
