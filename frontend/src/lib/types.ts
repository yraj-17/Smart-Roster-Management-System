// Shapes returned by the FastAPI backend (see backend/app/schemas.py and services).

export type EntryStatus = 'WORK' | 'WEEKLY_OFF' | 'LEAVE' | 'COMP_OFF' | 'HOLIDAY' | 'UNAVAILABLE'
export type SlotStatus = 'MET' | 'UNDERSTAFFED' | 'UNCOVERED' | 'NOT_REQUIRED'
export type ValidationStatus =
  | 'FULLY_COVERED' | 'PARTIALLY_COVERED' | 'INVALID' | 'INFEASIBLE' | 'SOLVER_TIMEOUT' | 'STALE'
export type VersionStatus = 'DRAFT' | 'PUBLISHED' | 'SUPERSEDED' | 'ARCHIVED'
export type Category = 'INTEGRITY' | 'EMPLOYEE_RULE' | 'COVERAGE' | 'PREFERENCE' | 'CONFIG' | 'SOLVER'
export type Role = 'PRIMARY' | 'BACKUP'

export interface Version {
  id: number
  plan_id: number
  version_no: number
  parent_version_id: number | null
  kind: 'GENERATED' | 'REOPTIMIZED' | 'MANUAL_CLONE'
  status: VersionStatus
  validation_status: ValidationStatus
  coverage_pct: number | null
  summary: {
    gaps: number; uncovered: number; understaffed: number
    hard_rule_violations: number; soft_issues: number; required_slot_days: number
  } | null
  solver_stats: Record<string, unknown> | null
  params: Record<string, unknown> | null
  notes: string | null
  created_by: string | null
  created_at: string
  published_by: string | null
  published_at: string | null
  year: number
  month: number
}

export interface Duty {
  duty_id: number
  slot_id: number
  label: string
  brand: string
  process: string
  duty_type: Role
  source: string
}

export interface Cell {
  entry_id: number
  date: string
  status: EntryStatus
  shift: string | null
  shift_id: number | null
  source: 'AUTO' | 'MANUAL' | 'REOPT'
  locked: boolean
  duties: Duty[]
}

export interface EmployeeRow {
  employee_id: number
  code: string
  name: string
  pod_id: number
  pod: string
  is_lead: boolean
  cells: (Cell | null)[]
  totals: Record<string, number>
}

export interface SlotInfo {
  slot_id: number
  brand_process_id: number
  brand_id: number
  brand: string
  process: string
  shift: string
  label: string
}

export interface CoverageCell {
  date: string
  required: number
  staffed: number
  backup_count: number
  status: SlotStatus
}

export interface CoverageRow extends SlotInfo {
  cells: (CoverageCell | null)[]
}

export interface RosterView {
  version: Version
  view: string
  ref_id: number | null
  days: string[]
  employees: EmployeeRow[]
  coverage: CoverageRow[]
}

export interface Suggestion {
  employee_id: number
  name: string
  action: 'ADD_DUTY' | 'WORK_ON_OFF_DAY' | 'CHANGE_SHIFT'
  assignment_id?: number
  role: Role
  score?: number
  reasons: string[]
  impact: string[]
  swap_off_date?: string | null
}

export interface GapPerson {
  employee_id: number
  name: string
  role: Role
  reason: string
  available: boolean
  can_work: boolean
}

export interface Conflict {
  id: number
  version_id: number
  type: string
  category: Category
  severity: 'HARD' | 'SOFT'
  date: string | null
  employee_id: number | null
  brand_process_shift_id: number | null
  message: string
  explanation: {
    required?: number; staffed?: number; gap_kind?: 'UNAVOIDABLE' | 'TRADE_OFF'; people?: GapPerson[]
    days?: string[]; [k: string]: unknown
  } | null
  suggestions: Suggestion[] | null
  status: 'OPEN' | 'RESOLVED' | 'ACKNOWLEDGED'
  ack_reason: string | null
  ack_by: string | null
  ack_at: string | null
}

export interface DiffEntry {
  employee_id: number
  employee: string
  date: string
  before: { status: EntryStatus; shift: string | null }
  after: { status: EntryStatus; shift: string | null }
}

export interface DiffDuty extends SlotInfo {
  employee_id: number
  employee: string
  date: string
  duty_type: Role
}

export interface RosterDiff {
  changed_entries: DiffEntry[]
  added_duties: DiffDuty[]
  removed_duties: DiffDuty[]
}

export interface DayResult {
  version: Version
  entry: { id: number; status: EntryStatus; shift_id: number | null; date: string; employee_id: number }
  duties: (SlotInfo & { id: number; duty_type: Role })[]
  issues_on_day: Conflict[]
}

export interface DayView {
  date: string
  working: { employee_id: number; name: string; pod: string; shift: string; duties: { label: string; duty_type: Role }[] }[]
  off: Record<string, { employee_id: number; name: string; pod: string }[]>
  gaps: (SlotInfo & { required: number; staffed: number; status: SlotStatus })[]
}

export interface ImpactMonth {
  year: number
  month: number
  version_id: number | null
  version_no?: number
  version_status?: VersionStatus
  message?: string
  brands_affected?: string[]
  duties_lost?: number
  new_gaps?: (SlotInfo & { date: string; required: number; staffed: number; status: SlotStatus; suggestions: Suggestion[] })[]
  coverage_pct_before?: number
  coverage_pct_after?: number
}

export interface Impact {
  employee_id: number
  employee: string
  date_from: string
  date_to: string
  months: ImpactMonth[]
}

export interface ChangeResult<T = unknown> {
  item: T
  stale_version_ids: number[]
  reoptimize_hint: { employee_ids: number[]; date_from: string; date_to: string } | null
}

export interface Dashboard {
  year: number
  month: number
  counts: Record<'employees' | 'brands' | 'processes' | 'pods' | 'brand_processes' | 'single_resource_brands' | 'multi_resource_brands', number>
  versions: { id: number; version_no: number; status: VersionStatus; kind: string; validation_status: ValidationStatus; coverage_pct: number | null }[]
  current: null | {
    version: Version
    conflicts: Record<string, { OPEN: number; ACKNOWLEDGED: number }>
    open_hard: number
    open_soft: number
    daily_coverage: { date: string; pct: number; staffed: number; required: number }[]
    brands_at_risk: { brand_id: number; brand: string; gap_slot_days: number }[]
    entry_status_counts: Record<string, number>
    backup_duties: number
    today: Record<string, number | string> | null
  }
  upcoming_leaves: { id: number; employee_id: number; employee: string; start_date: string; end_date: string; status: string; leave_type: string }[]
  pending_leave_requests: number
  pending_comp_off_credits: number
}

// ── master data ──
export interface Pod { id: number; name: string; lead_employee_id: number | null; active: boolean }
export interface OffDay { id?: number; day_of_week: number; kind: 'FIXED' | 'PREFERRED'; priority: number }
export interface Employee {
  id: number; code: string; name: string; email: string; pod_id: number; weekly_off_policy_id: number
  holiday_calendar_id: number | null; max_daily_load_pct: number; backup_stretch_pct: number; active: boolean
  off_days: OffDay[]
}
export interface Policy {
  id: number; name: string; min_offs_per_week: number; max_consecutive_work_days: number
  min_rest_hours: number; holidays_count_as_rest: boolean
}
export interface Process { id: number; code: string; name: string; description: string | null; active: boolean }
export interface Brand { id: number; code: string; name: string; holiday_calendar_id: number | null; notes: string | null; active: boolean }
export interface Shift { id: number; code: string; name: string; start_time: string; end_time: string }
export interface BrandProcess {
  id: number; brand_id: number; process_id: number; operating_days_mask: number; operates_on_holidays: boolean; active: boolean
}
export interface Slot { id: number; brand_process_id: number; shift_id: number; default_min_staff: number; active: boolean }
export interface CoverageRequirement {
  id: number; brand_process_shift_id: number; day_of_week: number | null; specific_date: string | null; min_staff: number; reason: string | null
}
export interface Assignment {
  id: number; employee_id: number; brand_process_id: number; shift_id: number | null; role: Role; load_pct: number
  effective_from: string; effective_to: string | null
}
export interface HolidayCalendar { id: number; name: string; region: string | null; is_default: boolean }
export interface Holiday { id: number; calendar_id: number; date: string; name: string; kind: 'NATIONAL' | 'REGIONAL' | 'OPTIONAL' }
export interface Leave {
  id: number; employee_id: number; start_date: string; end_date: string; leave_type: string; status: string
  reason: string | null; decided_by: string | null; decided_at: string | null
}
export interface Unavailability { id: number; employee_id: number; start_date: string; end_date: string; reason: string | null }
export interface CompOffCredit {
  id: number; employee_id: number; earned_on: string; source: string; source_version_id: number | null
  status: string; expires_on: string | null; consumed_on: string | null; note: string | null
}
export interface CompOffRequest { id: number; employee_id: number; date: string; credit_id: number; status: string; decided_by: string | null }
export interface AuditEntry {
  id: number; actor: string; entity_type: string; entity_id: number | null; version_id: number | null
  action: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null; reason: string | null; created_at: string
}
