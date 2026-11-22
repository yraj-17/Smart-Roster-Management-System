import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError, errorMessage } from '@/lib/api'
import type {
  Assignment, AuditEntry, Brand, BrandProcess, CompOffCredit, CompOffRequest, Conflict, CoverageRequirement,
  Dashboard, DayView, Employee, Holiday, HolidayCalendar, Leave, Pod, Policy, Process, RosterView, Shift, Slot,
  Unavailability, Version,
} from '@/lib/types'

// ── reads ────────────────────────────────────────────────────────────────────
const master = <T,>(key: string, path: string) => () =>
  useQuery({ queryKey: ['master', key], queryFn: () => api.get<T[]>(path), staleTime: 60_000 })

export const useEmployees = master<Employee>('employees', '/employees')
export const usePods = master<Pod>('pods', '/pods')
export const useBrands = master<Brand>('brands', '/brands')
export const useProcesses = master<Process>('processes', '/processes')
export const useShifts = master<Shift>('shifts', '/shifts')
export const useBrandProcesses = master<BrandProcess>('brand-processes', '/brand-processes')
export const useSlots = master<Slot>('slots', '/slots')
export const usePolicies = master<Policy>('policies', '/weekly-off-policies')
export const useCalendars = master<HolidayCalendar>('calendars', '/holiday-calendars')
export const useAssignments = master<Assignment>('assignments', '/assignments')
export const useCoverageRequirements = master<CoverageRequirement>('coverage-requirements', '/coverage-requirements')

export function useHolidays(calendarId: number | null | undefined, year?: number) {
  return useQuery({
    queryKey: ['master', 'holidays', calendarId, year],
    queryFn: () => api.get<Holiday[]>(`/holiday-calendars/${calendarId}/holidays`, { year }),
    enabled: !!calendarId,
  })
}

export function useVersion(id: number | null) {
  return useQuery({ queryKey: ['version', id], queryFn: () => api.get<Version>(`/versions/${id}`), enabled: !!id })
}

export function useRoster(id: number | null, view: string, refId: number | null) {
  return useQuery({
    queryKey: ['roster', id, view, refId],
    queryFn: () => api.get<RosterView>(`/versions/${id}/roster`, { view, ref_id: refId }),
    enabled: !!id && (view === 'company' || refId !== null),
  })
}

export function useDay(id: number | null, day: string | null) {
  return useQuery({
    queryKey: ['day', id, day],
    queryFn: () => api.get<DayView>(`/versions/${id}/days/${day}`),
    enabled: !!id && !!day,
  })
}

export function useConflicts(id: number | null, filters: Record<string, string | number | undefined> = {}) {
  return useQuery({
    queryKey: ['conflicts', id, filters],
    queryFn: () => api.get<Conflict[]>(`/versions/${id}/conflicts`, filters),
    enabled: !!id,
  })
}

export function useDashboard(year: number, month: number) {
  return useQuery({ queryKey: ['dashboard', year, month], queryFn: () => api.get<Dashboard>('/dashboard/summary', { year, month }) })
}

export function useLeaves(filters: Record<string, string | number | undefined> = {}) {
  return useQuery({ queryKey: ['leaves', filters], queryFn: () => api.get<Leave[]>('/leaves', filters) })
}
export function useUnavailability() {
  return useQuery({ queryKey: ['unavailability'], queryFn: () => api.get<Unavailability[]>('/unavailability') })
}
export function useCredits() {
  return useQuery({ queryKey: ['credits'], queryFn: () => api.get<CompOffCredit[]>('/comp-offs/credits') })
}
export function useCompRequests() {
  return useQuery({ queryKey: ['comp-requests'], queryFn: () => api.get<CompOffRequest[]>('/comp-offs/requests') })
}
export function useAudit(filters: Record<string, string | number | undefined>) {
  return useQuery({ queryKey: ['audit', filters], queryFn: () => api.get<AuditEntry[]>('/audit-log', filters) })
}

// ── writes ───────────────────────────────────────────────────────────────────
/** Everything derived from a roster version. */
export const ROSTER_KEYS = [['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['day'], ['audit']]

export function useApiMutation<TVars, TData = unknown>(
  fn: (vars: TVars) => Promise<TData>,
  opts: {
    success?: string | ((data: TData, vars: TVars) => string | null)
    invalidate?: unknown[][]
    onSuccess?: (data: TData, vars: TVars) => void
    onError?: (e: ApiError | Error, vars: TVars) => void
    silentError?: boolean
  } = {},
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: async (data, vars) => {
      await Promise.all((opts.invalidate ?? ROSTER_KEYS).map((k) => qc.invalidateQueries({ queryKey: k })))
      const msg = typeof opts.success === 'function' ? opts.success(data, vars) : opts.success
      if (msg) toast.success(msg)
      opts.onSuccess?.(data, vars)
    },
    onError: (e: Error, vars) => {
      if (!opts.silentError) {
        const conflict = e instanceof ApiError && e.isConflict
        toast.error(conflict ? 'Change rejected' : 'Request failed', { description: errorMessage(e) })
      }
      opts.onError?.(e, vars)
    },
  })
}

/** Default-calendar public holidays for a year, keyed by ISO date. */
export function useHolidayMap(year: number) {
  const cals = useCalendars()
  const def = cals.data?.find((c) => c.is_default)?.id
  const hol = useHolidays(def, year)
  return useMemo(() => Object.fromEntries((hol.data ?? []).map((h) => [h.date, h.name])), [hol.data])
}
