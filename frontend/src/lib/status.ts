// Visual vocabulary for statuses. Display only: the backend decides every status.
import type { Category, EntryStatus, SlotStatus, ValidationStatus, VersionStatus } from './types'

export const SLOT_STYLE: Record<SlotStatus, { label: string; cell: string; dot: string; text: string }> = {
  MET: { label: 'Met', cell: 'bg-emerald-100 text-emerald-900 hover:bg-emerald-200', dot: 'bg-emerald-500', text: 'text-emerald-700' },
  UNDERSTAFFED: { label: 'Understaffed', cell: 'bg-amber-200 text-amber-950 hover:bg-amber-300', dot: 'bg-amber-500', text: 'text-amber-700' },
  UNCOVERED: { label: 'Uncovered', cell: 'bg-red-500 text-white hover:bg-red-600', dot: 'bg-red-500', text: 'text-red-700' },
  NOT_REQUIRED: { label: 'Not required', cell: 'bg-slate-50 text-slate-300', dot: 'bg-slate-300', text: 'text-slate-500' },
}

// Entry cells: working days are coloured by shift, non-working days by reason.
export const SHIFT_STYLE: Record<string, string> = {
  MOR: 'bg-teal-100 text-teal-900 border-teal-200',
  GEN: 'bg-blue-100 text-blue-900 border-blue-200',
  EVE: 'bg-violet-100 text-violet-900 border-violet-200',
  NGT: 'bg-slate-700 text-slate-50 border-slate-700',
}

export const ENTRY_STYLE: Record<EntryStatus, { short: string; label: string; cell: string }> = {
  WORK: { short: '', label: 'Working', cell: 'bg-blue-100 text-blue-900 border-blue-200' },
  WEEKLY_OFF: { short: 'WO', label: 'Weekly off', cell: 'bg-white text-slate-400 border-slate-200' },
  LEAVE: { short: 'LV', label: 'Leave', cell: 'bg-orange-100 text-orange-800 border-orange-200' },
  COMP_OFF: { short: 'CO', label: 'Comp-off', cell: 'bg-fuchsia-100 text-fuchsia-800 border-fuchsia-200' },
  HOLIDAY: { short: 'PH', label: 'Public holiday', cell: 'bg-sky-50 text-sky-700 border-sky-200' },
  UNAVAILABLE: { short: 'NA', label: 'Unavailable', cell: 'bg-rose-50 text-rose-700 border-rose-200' },
}

export const VALIDATION_STYLE: Record<ValidationStatus, { label: string; badge: string; hint: string }> = {
  FULLY_COVERED: { label: 'Fully covered', badge: 'bg-emerald-50 text-emerald-700 border-emerald-200', hint: 'Every required shift is staffed and no rule is broken.' },
  PARTIALLY_COVERED: { label: 'Partially covered', badge: 'bg-amber-50 text-amber-800 border-amber-200', hint: 'Rules hold, but some required shifts are under- or un-staffed.' },
  INVALID: { label: 'Invalid', badge: 'bg-red-50 text-red-700 border-red-200', hint: 'A mandatory rule is broken. Cannot be published.' },
  INFEASIBLE: { label: 'Infeasible', badge: 'bg-red-50 text-red-700 border-red-200', hint: 'Locked rows contradict mandatory rules; the solver proved no roster exists.' },
  SOLVER_TIMEOUT: { label: 'Solver timeout', badge: 'bg-slate-100 text-slate-700 border-slate-300', hint: 'The solver hit its time limit before finding any roster.' },
  STALE: { label: 'Needs re-check', badge: 'bg-slate-100 text-slate-700 border-slate-300', hint: 'Inputs changed since the last validation.' },
}

export const VERSION_STYLE: Record<VersionStatus, string> = {
  DRAFT: 'bg-white text-slate-700 border-slate-300',
  PUBLISHED: 'bg-blue-600 text-white border-blue-600',
  SUPERSEDED: 'bg-slate-100 text-slate-500 border-slate-200',
  ARCHIVED: 'bg-slate-100 text-slate-400 border-slate-200',
}

/** How the conflicts panel groups categories. */
export const CONFLICT_GROUPS: { key: string; title: string; description: string; categories: Category[]; tone: string }[] = [
  {
    key: 'hard', title: 'Hard rule violations', categories: ['INTEGRITY', 'EMPLOYEE_RULE', 'SOLVER'], tone: 'red',
    description: 'Mandatory constraints. Must be fixed before publishing; cannot be acknowledged.',
  },
  {
    key: 'gaps', title: 'Coverage gaps', categories: ['COVERAGE'], tone: 'amber',
    description: 'Required shifts without enough people. Resolve with a suggestion or acknowledge with a reason.',
  },
  {
    key: 'soft', title: 'Preferences & warnings', categories: ['PREFERENCE', 'CONFIG'], tone: 'slate',
    description: 'Soft preferences and master-data warnings. Do not block publishing.',
  },
]

export const ACTION_LABEL: Record<string, string> = {
  ADD_DUTY: 'Add duty to their shift',
  WORK_ON_OFF_DAY: 'Work on their off day',
  CHANGE_SHIFT: 'Move to this shift',
}
