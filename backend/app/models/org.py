"""Organisation: pods, employees, rest policies, off-day preferences, holidays."""
from __future__ import annotations

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, enum_check


class WeeklyOffPolicy(IdMixin, TimestampMixin, Base):
    """Mandatory rest rules (hard constraints). Preferences live in employee_off_days."""
    __tablename__ = "weekly_off_policies"
    __table_args__ = (
        CheckConstraint("min_offs_per_week BETWEEN 0 AND 7", name="min_offs_range"),
        CheckConstraint("max_consecutive_work_days BETWEEN 1 AND 14", name="max_consec_range"),
        CheckConstraint("min_rest_hours BETWEEN 0 AND 24", name="min_rest_range"),
    )
    name: Mapped[str] = mapped_column(String(80), unique=True)
    min_offs_per_week: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    max_consecutive_work_days: Mapped[int] = mapped_column(SmallInteger, default=6, server_default="6")
    min_rest_hours: Mapped[int] = mapped_column(SmallInteger, default=11, server_default="11")
    holidays_count_as_rest: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class HolidayCalendar(IdMixin, TimestampMixin, Base):
    __tablename__ = "holiday_calendars"
    __table_args__ = (
        Index("uq_holiday_calendars_single_default", "is_default", unique=True,
              postgresql_where=text("is_default")),
    )
    name: Mapped[str] = mapped_column(String(80), unique=True)
    region: Mapped[str | None] = mapped_column(String(80))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    holidays: Mapped[list[PublicHoliday]] = relationship(back_populates="calendar",
                                                         cascade="all, delete-orphan")


class PublicHoliday(IdMixin, TimestampMixin, Base):
    __tablename__ = "public_holidays"
    __table_args__ = (
        UniqueConstraint("calendar_id", "date"),
        enum_check("kind", ["NATIONAL", "REGIONAL", "OPTIONAL"]),
        Index("ix_public_holidays_date", "date"),
    )
    calendar_id: Mapped[int] = mapped_column(ForeignKey("holiday_calendars.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="NATIONAL", server_default="NATIONAL")
    calendar: Mapped[HolidayCalendar] = relationship(back_populates="holidays")


class Pod(IdMixin, TimestampMixin, Base):
    __tablename__ = "pods"
    name: Mapped[str] = mapped_column(String(80), unique=True)
    lead_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL", use_alter=True, name="fk_pods_lead_employee_id_employees"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    lead: Mapped[Employee | None] = relationship(foreign_keys=[lead_employee_id], post_update=True)
    members: Mapped[list[Employee]] = relationship(back_populates="pod", foreign_keys="Employee.pod_id")


class Employee(IdMixin, TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint("max_daily_load_pct BETWEEN 1 AND 200", name="load_cap_range"),
        CheckConstraint("backup_stretch_pct BETWEEN 0 AND 100", name="stretch_range"),
        Index("ix_employees_pod_id", "pod_id"),
    )
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    pod_id: Mapped[int] = mapped_column(ForeignKey("pods.id", ondelete="RESTRICT"))
    weekly_off_policy_id: Mapped[int] = mapped_column(ForeignKey("weekly_off_policies.id", ondelete="RESTRICT"))
    holiday_calendar_id: Mapped[int | None] = mapped_column(
        ForeignKey("holiday_calendars.id", ondelete="SET NULL"))
    max_daily_load_pct: Mapped[int] = mapped_column(SmallInteger, default=100, server_default="100")
    backup_stretch_pct: Mapped[int] = mapped_column(SmallInteger, default=25, server_default="25")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    pod: Mapped[Pod] = relationship(back_populates="members", foreign_keys=[pod_id])
    policy: Mapped[WeeklyOffPolicy] = relationship()
    off_days: Mapped[list[EmployeeOffDay]] = relationship(back_populates="employee",
                                                          cascade="all, delete-orphan")


class EmployeeOffDay(IdMixin, TimestampMixin, Base):
    """FIXED = contractual weekly off (hard). PREFERRED = soft, weighted by priority."""
    __tablename__ = "employee_off_days"
    __table_args__ = (
        UniqueConstraint("employee_id", "day_of_week"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="dow_range"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
        enum_check("kind", ["FIXED", "PREFERRED"]),
    )
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"))
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(String(10))
    priority: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    employee: Mapped[Employee] = relationship(back_populates="off_days")
