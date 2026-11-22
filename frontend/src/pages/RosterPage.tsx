import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import { api } from '@/lib/api'
import { usePlan } from '@/lib/plan'
import type { Cell, CoverageRow, EmployeeRow, Version } from '@/lib/types'
import { useBrands, useEmployees, useHolidayMap, usePods, useProcesses, useRoster } from '@/hooks/queries'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { buttonVariants } from '@/components/ui/button'
import { EmptyState, ErrorState, Loading, NativeSelect, PageHeader } from '@/components/common'
import { EmployeeGrid, Legend, ProcessGrid } from '@/components/roster/RosterGrid'
import { DayEditor } from '@/components/roster/DayEditor'
import { GapPanel } from '@/components/roster/GapPanel'
import { DayPanel } from '@/components/roster/DayPanel'
import { RequireVersion } from '@/components/roster/RequireVersion'
import { VersionAlert, VersionSummary } from '@/components/roster/VersionSummary'

type Scope = 'company' | 'pod' | 'brand' | 'process' | 'employee'

export function RosterPage() {
  return (
    <>
      <PageHeader title="Monthly roster" description="Every employee's days, shifts and duties, with live coverage per brand-process shift. Click a cell to edit a day, a coverage cell to resolve a gap, or a date for who is working." />
      <RequireVersion>{(v) => <RosterBody version={v} />}</RequireVersion>
    </>
  )
}

function RosterBody({ version }: { version: Version }) {
  const { year } = usePlan()
  const [params, setParams] = useSearchParams()
  const [mode, setMode] = useState<'employees' | 'processes'>('employees')
  const [scope, setScope] = useState<Scope>('company')
  const [refId, setRefId] = useState<number | null>(null)
  const pods = usePods()
  const brands = useBrands()
  const processes = useProcesses()
  const employees = useEmployees()
  const holidays = useHolidayMap(year)
  const roster = useRoster(version.id, scope, scope === 'company' ? null : refId)

  const [editing, setEditing] = useState<{ row: EmployeeRow; cell: Cell } | null>(null)
  const [gap, setGap] = useState<{ row: CoverageRow; date: string } | null>(null)
  const [day, setDay] = useState<string | null>(null)

  // Deep link from Conflicts: ?employee=ID&date=YYYY-MM-DD opens that day.
  const focusEmp = Number(params.get('employee')) || null
  const focusDate = params.get('date')
  useEffect(() => {
    if (!focusEmp || !focusDate || !roster.data) return
    const row = roster.data.employees.find((r) => r.employee_id === focusEmp)
    const cell = row?.cells.find((c) => c?.date === focusDate)
    if (row && cell) setEditing({ row, cell })
  }, [focusEmp, focusDate, roster.data])

  const refOptions: { id: number; label: string }[] = useMemo(() => {
    switch (scope) {
      case 'pod': return (pods.data ?? []).map((p) => ({ id: p.id, label: p.name }))
      case 'brand': return (brands.data ?? []).filter((b) => b.active).map((b) => ({ id: b.id, label: b.name }))
      case 'process': return (processes.data ?? []).filter((p) => p.active).map((p) => ({ id: p.id, label: `${p.code} — ${p.name}` }))
      case 'employee': return (employees.data ?? []).filter((e) => e.active).map((e) => ({ id: e.id, label: `${e.name} (${e.code})` }))
      default: return []
    }
  }, [scope, pods.data, brands.data, processes.data, employees.data])

  useEffect(() => {
    if (scope !== 'company' && (refId === null || !refOptions.some((o) => o.id === refId))) setRefId(refOptions[0]?.id ?? null)
  }, [scope, refOptions, refId])

  return (
    <div className="space-y-3">
      <VersionAlert version={version} />
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <VersionSummary version={version} />
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={mode} onValueChange={(v) => setMode(v as typeof mode)}>
            <TabsList>
              <TabsTrigger value="employees">Employee view</TabsTrigger>
              <TabsTrigger value="processes">Process view</TabsTrigger>
            </TabsList>
          </Tabs>
          <NativeSelect aria-label="Scope" className="w-32" value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
            <option value="company">Company</option>
            <option value="pod">Pod</option>
            <option value="brand">Brand</option>
            <option value="process">Process</option>
            <option value="employee">Employee</option>
          </NativeSelect>
          {scope !== 'company' && (
            <NativeSelect aria-label="Filter" className="w-56" value={refId ?? ''} onChange={(e) => setRefId(Number(e.target.value))}>
              {refOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </NativeSelect>
          )}
          <a className={buttonVariants({ variant: 'outline', size: 'sm' })} href={api.downloadUrl(`/versions/${version.id}/export.csv`)}>
            <Download /> CSV
          </a>
        </div>
      </div>
      <Legend />
      {roster.isLoading ? <Loading rows={12} /> : roster.isError ? <ErrorState error={roster.error} onRetry={roster.refetch} /> : !roster.data?.employees.length ? (
        <EmptyState title="Nobody in this selection" description="No employee has an assignment in this scope for the month." />
      ) : mode === 'employees' ? (
        <EmployeeGrid
          data={roster.data}
          holidays={holidays}
          highlight={focusEmp && focusDate ? { employeeId: focusEmp, date: focusDate } : null}
          onCellClick={(row, cell) => setEditing({ row, cell })}
          onCoverageClick={(row, date) => setGap({ row, date })}
          onDayClick={setDay}
        />
      ) : (
        <ProcessGrid data={roster.data} holidays={holidays} onCoverageClick={(row, date) => setGap({ row, date })} onDayClick={setDay} />
      )}
      {editing && (
        <DayEditor version={version} row={editing.row} cell={editing.cell}
          onClose={() => { setEditing(null); if (focusEmp) setParams({}) }} />
      )}
      {gap && <GapPanel version={version} slotId={gap.row.slot_id} date={gap.date} label={gap.row.label} onClose={() => setGap(null)} />}
      {day && <DayPanel versionId={version.id} date={day} onClose={() => setDay(null)} />}
    </div>
  )
}
