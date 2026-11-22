"""initial schema

Also creates: the btree_gist extension (assignment overlap exclusion), the
circular pods -> employees FK, and trigger trg_roster_duty_eligibility.

Revision ID: 0001
Revises: 
Create Date: 2026-11-22 01:19:54.109193
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION roster_duty_eligibility() RETURNS trigger AS $$
DECLARE
    a assignments%ROWTYPE;
BEGIN
    SELECT * INTO a FROM assignments WHERE id = NEW.assignment_id;
    IF NOT (a.effective_from <= NEW.date AND (a.effective_to IS NULL OR NEW.date <= a.effective_to)) THEN
        RAISE EXCEPTION 'duty on % uses assignment % which is not effective on that date', NEW.date, a.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF a.shift_id IS NOT NULL AND a.shift_id <> NEW.shift_id THEN
        RAISE EXCEPTION 'assignment % does not allow shift %', a.id, NEW.shift_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM employees e
        JOIN brand_processes bp ON bp.id = NEW.brand_process_id
        JOIN brands b ON b.id = bp.brand_id
        JOIN processes p ON p.id = bp.process_id
        JOIN brand_process_shifts bps ON bps.id = NEW.brand_process_shift_id
        WHERE e.id = NEW.employee_id AND e.active AND bp.active AND b.active AND p.active AND bps.active
    ) THEN
        RAISE EXCEPTION 'employee, brand, process or shift slot is inactive for this duty'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_roster_duty_eligibility
    BEFORE INSERT OR UPDATE ON roster_duties
    FOR EACH ROW EXECUTE FUNCTION roster_duty_eligibility();
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table('holiday_calendars',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('region', sa.String(length=80), nullable=True),
    sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_holiday_calendars')),
    sa.UniqueConstraint('name', name=op.f('uq_holiday_calendars_name'))
    )
    op.create_index('uq_holiday_calendars_single_default', 'holiday_calendars', ['is_default'], unique=True, postgresql_where=sa.text('is_default'))
    op.create_table('pods',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('lead_employee_id', sa.BigInteger(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pods')),
    sa.UniqueConstraint('name', name=op.f('uq_pods_name'))
    )
    op.create_table('processes',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_processes')),
    sa.UniqueConstraint('code', name=op.f('uq_processes_code'))
    )
    op.create_table('roster_plans',
    sa.Column('year', sa.SmallInteger(), nullable=False),
    sa.Column('month', sa.SmallInteger(), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('month BETWEEN 1 AND 12', name=op.f('ck_roster_plans_month_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roster_plans')),
    sa.UniqueConstraint('year', 'month', name=op.f('uq_roster_plans_year_month'))
    )
    op.create_table('shifts',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('start_time <> end_time', name=op.f('ck_shifts_non_zero_length')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shifts')),
    sa.UniqueConstraint('code', name=op.f('uq_shifts_code'))
    )
    op.create_table('weekly_off_policies',
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('min_offs_per_week', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('max_consecutive_work_days', sa.SmallInteger(), server_default='6', nullable=False),
    sa.Column('min_rest_hours', sa.SmallInteger(), server_default='11', nullable=False),
    sa.Column('holidays_count_as_rest', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('max_consecutive_work_days BETWEEN 1 AND 14', name=op.f('ck_weekly_off_policies_max_consec_range')),
    sa.CheckConstraint('min_offs_per_week BETWEEN 0 AND 7', name=op.f('ck_weekly_off_policies_min_offs_range')),
    sa.CheckConstraint('min_rest_hours BETWEEN 0 AND 24', name=op.f('ck_weekly_off_policies_min_rest_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_weekly_off_policies')),
    sa.UniqueConstraint('name', name=op.f('uq_weekly_off_policies_name'))
    )
    op.create_table('brands',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('holiday_calendar_id', sa.BigInteger(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['holiday_calendar_id'], ['holiday_calendars.id'], name=op.f('fk_brands_holiday_calendar_id_holiday_calendars'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brands')),
    sa.UniqueConstraint('code', name=op.f('uq_brands_code'))
    )
    op.create_table('employees',
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('pod_id', sa.BigInteger(), nullable=False),
    sa.Column('weekly_off_policy_id', sa.BigInteger(), nullable=False),
    sa.Column('holiday_calendar_id', sa.BigInteger(), nullable=True),
    sa.Column('max_daily_load_pct', sa.SmallInteger(), server_default='100', nullable=False),
    sa.Column('backup_stretch_pct', sa.SmallInteger(), server_default='25', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('backup_stretch_pct BETWEEN 0 AND 100', name=op.f('ck_employees_stretch_range')),
    sa.CheckConstraint('max_daily_load_pct BETWEEN 1 AND 200', name=op.f('ck_employees_load_cap_range')),
    sa.ForeignKeyConstraint(['holiday_calendar_id'], ['holiday_calendars.id'], name=op.f('fk_employees_holiday_calendar_id_holiday_calendars'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['pod_id'], ['pods.id'], name=op.f('fk_employees_pod_id_pods'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['weekly_off_policy_id'], ['weekly_off_policies.id'], name=op.f('fk_employees_weekly_off_policy_id_weekly_off_policies'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employees')),
    sa.UniqueConstraint('code', name=op.f('uq_employees_code')),
    sa.UniqueConstraint('email', name=op.f('uq_employees_email'))
    )
    op.create_index('ix_employees_pod_id', 'employees', ['pod_id'], unique=False)
    op.create_table('public_holidays',
    sa.Column('calendar_id', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('kind', sa.String(length=16), server_default='NATIONAL', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('NATIONAL', 'REGIONAL', 'OPTIONAL')", name=op.f('ck_public_holidays_kind_valid')),
    sa.ForeignKeyConstraint(['calendar_id'], ['holiday_calendars.id'], name=op.f('fk_public_holidays_calendar_id_holiday_calendars'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_public_holidays')),
    sa.UniqueConstraint('calendar_id', 'date', name=op.f('uq_public_holidays_calendar_id_date'))
    )
    op.create_index('ix_public_holidays_date', 'public_holidays', ['date'], unique=False)
    op.create_table('roster_versions',
    sa.Column('plan_id', sa.BigInteger(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('parent_version_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('validation_status', sa.String(length=20), nullable=False),
    sa.Column('coverage_pct', sa.Numeric(precision=5, scale=2), nullable=True),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('solver_stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=80), nullable=True),
    sa.Column('published_by', sa.String(length=80), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('GENERATED', 'REOPTIMIZED', 'MANUAL_CLONE')", name=op.f('ck_roster_versions_kind_valid')),
    sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'ARCHIVED')", name=op.f('ck_roster_versions_status_valid')),
    sa.CheckConstraint("validation_status IN ('FULLY_COVERED', 'PARTIALLY_COVERED', 'INVALID', 'INFEASIBLE', 'SOLVER_TIMEOUT', 'STALE')", name=op.f('ck_roster_versions_validation_status_valid')),
    sa.ForeignKeyConstraint(['parent_version_id'], ['roster_versions.id'], name=op.f('fk_roster_versions_parent_version_id_roster_versions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['plan_id'], ['roster_plans.id'], name=op.f('fk_roster_versions_plan_id_roster_plans'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roster_versions')),
    sa.UniqueConstraint('plan_id', 'version_no', name=op.f('uq_roster_versions_plan_id_version_no'))
    )
    op.create_index('uq_roster_versions_one_published', 'roster_versions', ['plan_id'], unique=True, postgresql_where=sa.text("status = 'PUBLISHED'"))
    op.create_table('audit_log',
    sa.Column('actor', sa.String(length=80), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.BigInteger(), nullable=True),
    sa.Column('version_id', sa.BigInteger(), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['roster_versions.id'], name=op.f('fk_audit_log_version_id_roster_versions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_log_version_created', 'audit_log', ['version_id', 'created_at'], unique=False)
    op.create_table('brand_processes',
    sa.Column('brand_id', sa.BigInteger(), nullable=False),
    sa.Column('process_id', sa.BigInteger(), nullable=False),
    sa.Column('operating_days_mask', sa.SmallInteger(), server_default='127', nullable=False),
    sa.Column('operates_on_holidays', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('operating_days_mask BETWEEN 0 AND 127', name=op.f('ck_brand_processes_mask_range')),
    sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], name=op.f('fk_brand_processes_brand_id_brands'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['process_id'], ['processes.id'], name=op.f('fk_brand_processes_process_id_processes'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brand_processes')),
    sa.UniqueConstraint('brand_id', 'process_id', name=op.f('uq_brand_processes_brand_id_process_id'))
    )
    op.create_table('comp_off_credits',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('earned_on', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('source_version_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('expires_on', sa.Date(), nullable=True),
    sa.Column('consumed_on', sa.Date(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('HOLIDAY_WORK', 'REST_DAY_WORK', 'MANUAL')", name=op.f('ck_comp_off_credits_source_valid')),
    sa.CheckConstraint("status IN ('PENDING', 'AVAILABLE', 'REJECTED', 'CONSUMED', 'EXPIRED', 'REVERSED')", name=op.f('ck_comp_off_credits_status_valid')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_comp_off_credits_employee_id_employees'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_version_id'], ['roster_versions.id'], name=op.f('fk_comp_off_credits_source_version_id_roster_versions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comp_off_credits')),
    sa.UniqueConstraint('employee_id', 'earned_on', 'source', name=op.f('uq_comp_off_credits_employee_id_earned_on_source'))
    )
    op.create_index('ix_comp_off_credits_employee_status', 'comp_off_credits', ['employee_id', 'status'], unique=False)
    op.create_table('employee_off_days',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('day_of_week', sa.SmallInteger(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('priority', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('FIXED', 'PREFERRED')", name=op.f('ck_employee_off_days_kind_valid')),
    sa.CheckConstraint('day_of_week BETWEEN 0 AND 6', name=op.f('ck_employee_off_days_dow_range')),
    sa.CheckConstraint('priority BETWEEN 1 AND 5', name=op.f('ck_employee_off_days_priority_range')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_employee_off_days_employee_id_employees'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employee_off_days')),
    sa.UniqueConstraint('employee_id', 'day_of_week', name=op.f('uq_employee_off_days_employee_id_day_of_week'))
    )
    op.create_table('leaves',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('leave_type', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('decided_by', sa.String(length=80), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("leave_type IN ('PLANNED', 'SICK', 'CASUAL', 'OTHER')", name=op.f('ck_leaves_leave_type_valid')),
    sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')", name=op.f('ck_leaves_status_valid')),
    sa.CheckConstraint('end_date >= start_date', name=op.f('ck_leaves_date_order')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_leaves_employee_id_employees'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leaves'))
    )
    op.create_index('ix_leaves_employee_dates', 'leaves', ['employee_id', 'start_date', 'end_date'], unique=False)
    op.create_index('ix_leaves_status', 'leaves', ['status'], unique=False)
    op.create_table('roster_entries',
    sa.Column('version_id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('shift_id', sa.BigInteger(), nullable=True),
    sa.Column('source', sa.String(length=8), nullable=False),
    sa.Column('is_locked', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'WORK') = (shift_id IS NOT NULL)", name=op.f('ck_roster_entries_shift_iff_work')),
    sa.CheckConstraint("source IN ('AUTO', 'MANUAL', 'REOPT')", name=op.f('ck_roster_entries_source_valid')),
    sa.CheckConstraint("status IN ('WORK', 'WEEKLY_OFF', 'LEAVE', 'COMP_OFF', 'HOLIDAY', 'UNAVAILABLE')", name=op.f('ck_roster_entries_status_valid')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_roster_entries_employee_id_employees'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], name=op.f('fk_roster_entries_shift_id_shifts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['version_id'], ['roster_versions.id'], name=op.f('fk_roster_entries_version_id_roster_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roster_entries')),
    sa.UniqueConstraint('id', 'version_id', 'employee_id', 'date', 'shift_id', 'status', name='uq_roster_entries_duty_target'),
    sa.UniqueConstraint('version_id', 'employee_id', 'date', name=op.f('uq_roster_entries_version_id_employee_id_date'))
    )
    op.create_index('ix_roster_entries_version_date', 'roster_entries', ['version_id', 'date'], unique=False)
    op.create_table('unavailability',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_date >= start_date', name=op.f('ck_unavailability_date_order')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_unavailability_employee_id_employees'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_unavailability'))
    )
    op.create_index('ix_unavailability_employee_dates', 'unavailability', ['employee_id', 'start_date', 'end_date'], unique=False)
    op.create_table('assignments',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('brand_process_id', sa.BigInteger(), nullable=False),
    sa.Column('shift_id', sa.BigInteger(), nullable=True),
    sa.Column('role', sa.String(length=8), nullable=False),
    sa.Column('load_pct', sa.SmallInteger(), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    postgresql.ExcludeConstraint((sa.column('employee_id'), '='), (sa.column('brand_process_id'), '='), (sa.text("daterange(effective_from, effective_to, '[]')"), '&&'), using='gist', name='ex_assignments_no_overlap'),
    sa.CheckConstraint("role IN ('PRIMARY', 'BACKUP')", name=op.f('ck_assignments_role_valid')),
    sa.CheckConstraint('effective_to IS NULL OR effective_to >= effective_from', name=op.f('ck_assignments_date_order')),
    sa.CheckConstraint('load_pct BETWEEN 1 AND 100', name=op.f('ck_assignments_load_range')),
    sa.ForeignKeyConstraint(['brand_process_id'], ['brand_processes.id'], name=op.f('fk_assignments_brand_process_id_brand_processes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_assignments_employee_id_employees'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], name=op.f('fk_assignments_shift_id_shifts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assignments')),
    sa.UniqueConstraint('id', 'employee_id', 'brand_process_id', 'role', name='uq_assignments_identity')
    )
    op.create_index('ix_assignments_bp_role', 'assignments', ['brand_process_id', 'role'], unique=False)
    op.create_index('ix_assignments_employee', 'assignments', ['employee_id'], unique=False)
    op.create_table('brand_process_shifts',
    sa.Column('brand_process_id', sa.BigInteger(), nullable=False),
    sa.Column('shift_id', sa.BigInteger(), nullable=False),
    sa.Column('default_min_staff', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('default_min_staff >= 0', name=op.f('ck_brand_process_shifts_min_staff_non_negative')),
    sa.ForeignKeyConstraint(['brand_process_id'], ['brand_processes.id'], name=op.f('fk_brand_process_shifts_brand_process_id_brand_processes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], name=op.f('fk_brand_process_shifts_shift_id_shifts'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_brand_process_shifts')),
    sa.UniqueConstraint('brand_process_id', 'shift_id', name=op.f('uq_brand_process_shifts_brand_process_id_shift_id')),
    sa.UniqueConstraint('id', 'brand_process_id', 'shift_id', name='uq_bps_id_bp_shift')
    )
    op.create_table('comp_off_requests',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('credit_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('decided_by', sa.String(length=80), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')", name=op.f('ck_comp_off_requests_status_valid')),
    sa.ForeignKeyConstraint(['credit_id'], ['comp_off_credits.id'], name=op.f('fk_comp_off_requests_credit_id_comp_off_credits'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_comp_off_requests_employee_id_employees'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comp_off_requests'))
    )
    op.create_index('ix_comp_off_requests_employee_date', 'comp_off_requests', ['employee_id', 'date'], unique=False)
    op.create_index('uq_comp_off_requests_active_credit', 'comp_off_requests', ['credit_id'], unique=True, postgresql_where=sa.text("status IN ('REQUESTED','APPROVED')"))
    op.create_table('coverage_requirements',
    sa.Column('brand_process_shift_id', sa.BigInteger(), nullable=False),
    sa.Column('day_of_week', sa.SmallInteger(), nullable=True),
    sa.Column('specific_date', sa.Date(), nullable=True),
    sa.Column('min_staff', sa.SmallInteger(), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('(day_of_week IS NULL) <> (specific_date IS NULL)', name=op.f('ck_coverage_requirements_exactly_one_target')),
    sa.CheckConstraint('day_of_week BETWEEN 0 AND 6', name=op.f('ck_coverage_requirements_dow_range')),
    sa.CheckConstraint('min_staff >= 0', name=op.f('ck_coverage_requirements_min_staff_non_negative')),
    sa.ForeignKeyConstraint(['brand_process_shift_id'], ['brand_process_shifts.id'], name=op.f('fk_coverage_requirements_brand_process_shift_id_brand_process_shifts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_coverage_requirements')),
    sa.UniqueConstraint('brand_process_shift_id', 'day_of_week', name='uq_cov_req_slot_dow'),
    sa.UniqueConstraint('brand_process_shift_id', 'specific_date', name='uq_cov_req_slot_date')
    )
    op.create_table('roster_conflicts',
    sa.Column('version_id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=16), nullable=False),
    sa.Column('severity', sa.String(length=4), nullable=False),
    sa.Column('date', sa.Date(), nullable=True),
    sa.Column('employee_id', sa.BigInteger(), nullable=True),
    sa.Column('brand_process_shift_id', sa.BigInteger(), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('explanation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('suggestions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('ack_reason', sa.Text(), nullable=True),
    sa.Column('ack_by', sa.String(length=80), nullable=True),
    sa.Column('ack_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('INTEGRITY', 'EMPLOYEE_RULE', 'COVERAGE', 'PREFERENCE', 'CONFIG', 'SOLVER')", name=op.f('ck_roster_conflicts_category_valid')),
    sa.CheckConstraint("severity IN ('HARD', 'SOFT')", name=op.f('ck_roster_conflicts_severity_valid')),
    sa.CheckConstraint("status IN ('OPEN', 'RESOLVED', 'ACKNOWLEDGED')", name=op.f('ck_roster_conflicts_status_valid')),
    sa.ForeignKeyConstraint(['brand_process_shift_id'], ['brand_process_shifts.id'], name=op.f('fk_roster_conflicts_brand_process_shift_id_brand_process_shifts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_roster_conflicts_employee_id_employees'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['version_id'], ['roster_versions.id'], name=op.f('fk_roster_conflicts_version_id_roster_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roster_conflicts'))
    )
    op.create_index('ix_roster_conflicts_version_date', 'roster_conflicts', ['version_id', 'date'], unique=False)
    op.create_index('ix_roster_conflicts_version_status', 'roster_conflicts', ['version_id', 'status', 'severity'], unique=False)
    op.create_table('roster_coverage',
    sa.Column('version_id', sa.BigInteger(), nullable=False),
    sa.Column('brand_process_shift_id', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('required', sa.SmallInteger(), nullable=False),
    sa.Column('staffed', sa.SmallInteger(), nullable=False),
    sa.Column('primary_count', sa.SmallInteger(), nullable=False),
    sa.Column('backup_count', sa.SmallInteger(), nullable=False),
    sa.Column('backup_capacity', sa.SmallInteger(), nullable=False),
    sa.Column('status', sa.String(length=14), nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.CheckConstraint("status IN ('MET', 'UNDERSTAFFED', 'UNCOVERED', 'NOT_REQUIRED')", name=op.f('ck_roster_coverage_status_valid')),
    sa.ForeignKeyConstraint(['brand_process_shift_id'], ['brand_process_shifts.id'], name=op.f('fk_roster_coverage_brand_process_shift_id_brand_process_shifts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['roster_versions.id'], name=op.f('fk_roster_coverage_version_id_roster_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roster_coverage')),
    sa.UniqueConstraint('version_id', 'brand_process_shift_id', 'date', name=op.f('uq_roster_coverage_version_id_brand_process_shift_id_date'))
    )
    op.create_index('ix_roster_coverage_version_status', 'roster_coverage', ['version_id', 'status'], unique=False)
    op.create_table('roster_duties',
    sa.Column('version_id', sa.BigInteger(), nullable=False),
    sa.Column('entry_id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('shift_id', sa.BigInteger(), nullable=False),
    sa.Column('entry_status', sa.String(length=12), server_default='WORK', nullable=False),
    sa.Column('brand_process_shift_id', sa.BigInteger(), nullable=False),
    sa.Column('brand_process_id', sa.BigInteger(), nullable=False),
    sa.Column('assignment_id', sa.BigInteger(), nullable=False),
    sa.Column('duty_type', sa.String(length=8), nullable=False),
    sa.Column('source', sa.String(length=8), nullable=False),
    sa.Column('is_locked', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("duty_type IN ('PRIMARY', 'BACKUP')", name=op.f('ck_roster_duties_duty_type_valid')),
    sa.CheckConstraint("entry_status = 'WORK'", name=op.f('ck_roster_duties_entry_must_be_work')),
    sa.CheckConstraint("source IN ('AUTO', 'MANUAL', 'REOPT')", name=op.f('ck_roster_duties_source_valid')),
    sa.ForeignKeyConstraint(['assignment_id', 'employee_id', 'brand_process_id', 'duty_type'], ['assignments.id', 'assignments.employee_id', 'assignments.brand_process_id', 'assignments.role'], name='fk_roster_duties_assignment', onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['brand_process_shift_id', 'brand_process_id', 'shift_id'], ['brand_process_shifts.id', 'brand_process_shifts.brand_process_id', 'brand_process_shifts.shift_id'], name='fk_roster_duties_slot', onupdate='RESTRICT', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_roster_duties_employee_id_employees'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['entry_id', 'version_id', 'employee_id', 'date', 'shift_id', 'entry_status'], ['roster_entries.id', 'roster_entries.version_id', 'roster_entries.employee_id', 'roster_entries.date', 'roster_entries.shift_id', 'roster_entries.status'], name='fk_roster_duties_entry', onupdate='RESTRICT', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version_id'], ['roster_versions.id'], name=op.f('fk_roster_duties_version_id_roster_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roster_duties')),
    sa.UniqueConstraint('version_id', 'employee_id', 'date', 'brand_process_id', name='uq_roster_duties_no_double_count')
    )
    op.create_index('ix_roster_duties_coverage', 'roster_duties', ['version_id', 'date', 'brand_process_shift_id'], unique=False)
    op.create_index('ix_roster_duties_employee_day', 'roster_duties', ['version_id', 'employee_id', 'date'], unique=False)
    op.create_foreign_key('fk_pods_lead_employee_id_employees', 'pods', 'employees',
                          ['lead_employee_id'], ['id'], ondelete='SET NULL')
    op.execute(TRIGGER_SQL)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_roster_duty_eligibility ON roster_duties")
    op.execute("DROP FUNCTION IF EXISTS roster_duty_eligibility()")
    op.drop_constraint('fk_pods_lead_employee_id_employees', 'pods', type_='foreignkey')
    op.drop_index('ix_roster_duties_employee_day', table_name='roster_duties')
    op.drop_index('ix_roster_duties_coverage', table_name='roster_duties')
    op.drop_table('roster_duties')
    op.drop_index('ix_roster_coverage_version_status', table_name='roster_coverage')
    op.drop_table('roster_coverage')
    op.drop_index('ix_roster_conflicts_version_status', table_name='roster_conflicts')
    op.drop_index('ix_roster_conflicts_version_date', table_name='roster_conflicts')
    op.drop_table('roster_conflicts')
    op.drop_table('coverage_requirements')
    op.drop_index('uq_comp_off_requests_active_credit', table_name='comp_off_requests', postgresql_where=sa.text("status IN ('REQUESTED','APPROVED')"))
    op.drop_index('ix_comp_off_requests_employee_date', table_name='comp_off_requests')
    op.drop_table('comp_off_requests')
    op.drop_table('brand_process_shifts')
    op.drop_index('ix_assignments_employee', table_name='assignments')
    op.drop_index('ix_assignments_bp_role', table_name='assignments')
    op.drop_table('assignments')
    op.drop_index('ix_unavailability_employee_dates', table_name='unavailability')
    op.drop_table('unavailability')
    op.drop_index('ix_roster_entries_version_date', table_name='roster_entries')
    op.drop_table('roster_entries')
    op.drop_index('ix_leaves_status', table_name='leaves')
    op.drop_index('ix_leaves_employee_dates', table_name='leaves')
    op.drop_table('leaves')
    op.drop_table('employee_off_days')
    op.drop_index('ix_comp_off_credits_employee_status', table_name='comp_off_credits')
    op.drop_table('comp_off_credits')
    op.drop_table('brand_processes')
    op.drop_index('ix_audit_log_version_created', table_name='audit_log')
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index('uq_roster_versions_one_published', table_name='roster_versions', postgresql_where=sa.text("status = 'PUBLISHED'"))
    op.drop_table('roster_versions')
    op.drop_index('ix_public_holidays_date', table_name='public_holidays')
    op.drop_table('public_holidays')
    op.drop_index('ix_employees_pod_id', table_name='employees')
    op.drop_table('employees')
    op.drop_table('brands')
    op.drop_table('weekly_off_policies')
    op.drop_table('shifts')
    op.drop_table('roster_plans')
    op.drop_table('processes')
    op.drop_table('pods')
    op.drop_index('uq_holiday_calendars_single_default', table_name='holiday_calendars', postgresql_where=sa.text('is_default'))
    op.drop_table('holiday_calendars')
    # ### end Alembic commands ###
