import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useHolidayMap } from '@/hooks/queries'
import { usePlan } from '@/lib/plan'
import { DOW, dow, parseDate } from '@/lib/format'
import { SLOT_STYLE } from '@/lib/status'
import type { CoverageRow, SlotStatus, Version } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorState, Loading, NativeSelect, PageHeader, Stat } from '@/components/common'
import { CoverageCellButton } from '@/components/roster/RosterGrid'
import { GapPanel } from '@/components/roster/GapPanel'
import { RequireVersion } from '@/components/roster/RequireVersion'
import { VersionAlert, VersionSummary } from '@/components/roster/VersionSummary'

export function CoveragePage() {
  return (
    <>
      <PageHeader title="Coverage heatmap" description="Each brand-process shift against each day. Status comes from the independent validator: an employee counts once per shift, and only valid duties count." />
      <RequireVersion>{(v) => <CoverageBody version={v} />}</RequireVersion>
    </>
  )
}

function CoverageBody({ version }: { version: Version }) {
  const { year } = usePlan()
  const q = useQuery({ queryKey: ['roster', version.id, 'coverage'], queryFn: () => api.get<CoverageRow[]>(`/versions/${version.id}/coverage`) })
  const holidays = useHolidayMap(year)
  const [brand, setBrand] = useState('')
  const [process, setProcess] = useState('')
  const [gapsOnly, setGapsOnly] = useState(false)
  const [gap, setGap] = useState<{ row: CoverageRow; date: string } | null>(null)

  const rows = useMemo(() => (q.data ?? []).filter((r) =>
    (!brand || r.brand === brand) && (!process || r.process === process) &&
    (!gapsOnly || r.cells.some((c) => c && (c.status === 'UNCOVERED' || c.status === 'UNDERSTAFFED')))), [q.data, brand, process, gapsOnly])
  const counts = useMemo(() => {
    const c: Record<SlotStatus, number> = { MET: 0, UNDERSTAFFED: 0, UNCOVERED: 0, NOT_REQUIRED: 0 }
    for (const r of q.data ?? []) for (const cell of r.cells) if (cell) c[cell.status]++
    return c
  }, [q.data])
  const days = q.data?.[0]?.cells.map((c, i) => c?.date ?? String(i)) ?? []

  if (q.isLoading) return <Loading rows={10} />
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />
  return (
    <div className="space-y-4">
      <VersionAlert version={version} />
      <VersionSummary version={version} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {(['MET', 'UNDERSTAFFED', 'UNCOVERED', 'NOT_REQUIRED'] as SlotStatus[]).map((s) => (
          <button key={s} type="button" className="text-left" onClick={() => setGapsOnly(s === 'UNCOVERED' || s === 'UNDERSTAFFED')}>
            <Stat label={`${SLOT_STYLE[s].label} shift-days`} value={counts[s]}
              tone={s === 'UNCOVERED' ? 'red' : s === 'UNDERSTAFFED' ? 'amber' : s === 'MET' ? 'green' : undefined} />
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <NativeSelect aria-label="Brand" className="w-52" value={brand} onChange={(e) => setBrand(e.target.value)}>
          <option value="">All brands</option>
          {[...new Set((q.data ?? []).map((r) => r.brand))].sort().map((b) => <option key={b}>{b}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="Process" className="w-36" value={process} onChange={(e) => setProcess(e.target.value)}>
          <option value="">All processes</option>
          {[...new Set((q.data ?? []).map((r) => r.process))].sort().map((p) => <option key={p}>{p}</option>)}
        </NativeSelect>
        <label className="flex items-center gap-2 text-sm"><Checkbox checked={gapsOnly} onCheckedChange={(v) => setGapsOnly(!!v)} />Only rows with gaps</label>
        <span className="text-xs text-muted-foreground">{rows.length} of {q.data?.length ?? 0} shifts</span>
      </div>
      <div className="max-h-[calc(100vh-20rem)] overflow-auto rounded-lg border bg-background" data-testid="coverage-heatmap">
        <table className="border-separate border-spacing-0 text-sm">
          <thead className="sticky top-0 z-20 bg-background">
            <tr>
              <th className="sticky left-0 z-30 min-w-56 border-r border-b bg-background px-3 py-2 text-left text-xs font-medium text-muted-foreground">Brand · process · shift</th>
              {days.map((d) => (
                <th key={d} className={cn('w-8 min-w-8 border-b py-1 text-center font-normal', dow(d) >= 5 && 'bg-slate-100/80', holidays[d] && 'bg-sky-50')} title={holidays[d]}>
                  <span className="block text-[10px] text-muted-foreground uppercase">{DOW[dow(d)].slice(0, 1)}</span>
                  <span className="text-xs font-semibold tabular">{parseDate(d).getDate()}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.slot_id}>
                <th scope="row" className="sticky left-0 z-10 border-r border-b bg-background px-3 py-1 text-left text-xs font-medium">
                  {r.brand} <span className="font-normal text-muted-foreground">· {r.process} · {r.shift}</span>
                </th>
                {r.cells.map((c, i) => (
                  <td key={days[i]} className="w-8 min-w-8 border-b p-0.5">
                    <CoverageCellButton row={r} cell={c} compact onClick={() => setGap({ row: r, date: days[i] })} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {gap && <GapPanel version={version} slotId={gap.row.slot_id} date={gap.date} label={gap.row.label} onClose={() => setGap(null)} />}
    </div>
  )
}
