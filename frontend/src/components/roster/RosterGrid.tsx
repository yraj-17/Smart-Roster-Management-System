import { Fragment, useMemo } from 'react'
import { Lock } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DOW, dow, initials, parseDate } from '@/lib/format'
import { ENTRY_STYLE, SHIFT_STYLE, SLOT_STYLE } from '@/lib/status'
import type { Cell, CoverageRow, EmployeeRow, RosterView } from '@/lib/types'

const DAY_W = 'w-10 min-w-10'

export interface GridHandlers {
  onCellClick?: (row: EmployeeRow, cell: Cell) => void
  onCoverageClick?: (row: CoverageRow, date: string) => void
  onDayClick?: (date: string) => void
}

function DayHeader({ days, holidays, onDayClick, label }: {
  days: string[]; holidays: Record<string, string>; onDayClick?: (d: string) => void; label: string
}) {
  return (
    <thead className="sticky top-0 z-20 bg-background">
      <tr>
        <th className="sticky left-0 z-30 min-w-56 border-b border-r bg-background px-3 py-2 text-left text-xs font-medium text-muted-foreground">
          {label}
        </th>
        {days.map((d) => {
          const w = dow(d)
          const hol = holidays[d]
          return (
            <th key={d} className={cn(DAY_W, 'border-b px-0 py-1 text-center font-normal', w >= 5 && 'bg-slate-100/80', hol && 'bg-sky-50')}>
              <button
                type="button"
                onClick={() => onDayClick?.(d)}
                title={hol ? `${hol} — click for who is working` : 'Click for who is working'}
                className="flex w-full flex-col items-center rounded py-0.5 hover:bg-slate-200/60"
              >
                <span className={cn('text-[10px] uppercase', w >= 5 ? 'text-slate-600' : 'text-muted-foreground')}>{DOW[w].slice(0, 2)}</span>
                <span className="text-xs font-semibold tabular">{parseDate(d).getDate()}</span>
                {hol && <span className="mt-0.5 size-1.5 rounded-full bg-sky-500" />}
              </button>
            </th>
          )
        })}
      </tr>
    </thead>
  )
}

function cellTitle(row: EmployeeRow, c: Cell, holiday?: string) {
  const lines = [`${row.name} — ${c.date}`, c.status === 'WORK' ? `Working ${c.shift} shift` : ENTRY_STYLE[c.status].label]
  if (holiday) lines.push(`Public holiday: ${holiday}`)
  for (const d of c.duties) lines.push(`• ${d.label}${d.duty_type === 'BACKUP' ? ' (backup)' : ''}`)
  if (c.locked) lines.push(`Manual edit (${c.source.toLowerCase()}) — kept by re-optimisation`)
  return lines.join('\n')
}

function EntryCell({ row, c, holiday, onClick, highlight }: {
  row: EmployeeRow; c: Cell | null; holiday?: string; onClick?: () => void; highlight: boolean
}) {
  if (!c) return <td className={cn(DAY_W, 'border-b')} />
  const working = c.status === 'WORK'
  const style = working ? SHIFT_STYLE[c.shift ?? ''] ?? ENTRY_STYLE.WORK.cell : ENTRY_STYLE[c.status].cell
  const backup = c.duties.some((d) => d.duty_type === 'BACKUP')
  return (
    <td className={cn(DAY_W, 'border-b p-0.5', dow(c.date) >= 5 && 'bg-slate-50')}>
      <button
        type="button"
        onClick={onClick}
        title={cellTitle(row, c, holiday)}
        data-testid={`cell-${row.employee_id}-${c.date}`}
        className={cn(
          'relative flex h-9 w-full flex-col items-center justify-center rounded border text-[10px] leading-tight font-semibold transition-shadow hover:ring-2 hover:ring-blue-400',
          style,
          highlight && 'ring-2 ring-offset-1 ring-blue-600',
        )}
      >
        <span>{working ? c.shift : ENTRY_STYLE[c.status].short}</span>
        {working && <span className="font-normal opacity-75 tabular">{c.duties.length}</span>}
        {backup && <span className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-amber-500" aria-label="backup duty" />}
        {c.locked && <Lock className="absolute bottom-0.5 left-0.5 size-2.5 opacity-70" aria-label="manual" />}
      </button>
    </td>
  )
}

export function CoverageCellButton({ row, cell, onClick, compact }: {
  row: CoverageRow; cell: CoverageRow['cells'][number]; onClick?: () => void; compact?: boolean
}) {
  if (!cell) return <div className="h-7" />
  const s = SLOT_STYLE[cell.status]
  const clickable = cell.status === 'UNDERSTAFFED' || cell.status === 'UNCOVERED' || cell.status === 'MET'
  return (
    <button
      type="button"
      disabled={!clickable}
      onClick={onClick}
      data-testid={`cov-${row.slot_id}-${cell.date}`}
      data-status={cell.status}
      title={`${row.label} — ${cell.date}\n${s.label}: ${cell.staffed}/${cell.required} staffed${cell.backup_count ? ` (${cell.backup_count} backup)` : ''}`}
      className={cn('flex h-7 w-full items-center justify-center rounded text-[10px] font-semibold tabular transition-colors', s.cell,
        !clickable && 'cursor-default')}
    >
      {cell.status === 'NOT_REQUIRED' ? '·' : compact ? '' : `${cell.staffed}/${cell.required}`}
    </button>
  )
}

function CoverageRows({ rows, days, onCoverageClick }: { rows: CoverageRow[]; days: string[]; onCoverageClick?: GridHandlers['onCoverageClick'] }) {
  return (
    <>
      <tr>
        <td colSpan={days.length + 1} className="sticky left-0 border-y bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
          Coverage (staffed / required per shift)
        </td>
      </tr>
      {rows.map((r) => (
        <tr key={r.slot_id}>
          <th scope="row" className="sticky left-0 z-10 border-r border-b bg-background px-3 py-1 text-left text-xs font-medium">
            <span className="block truncate" title={r.label}>{r.brand}</span>
            <span className="text-[11px] font-normal text-muted-foreground">{r.process} · {r.shift}</span>
          </th>
          {r.cells.map((c, i) => (
            <td key={days[i]} className={cn(DAY_W, 'border-b p-0.5')}>
              <CoverageCellButton row={r} cell={c} onClick={() => onCoverageClick?.(r, days[i])} />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

/** Employee view: one row per employee, grouped by pod, with coverage rows below. */
export function EmployeeGrid({ data, holidays, highlight, showCoverage = true, ...h }: GridHandlers & {
  data: RosterView; holidays: Record<string, string>; highlight?: { employeeId: number; date: string } | null; showCoverage?: boolean
}) {
  const groups = useMemo(() => {
    const g = new Map<string, EmployeeRow[]>()
    for (const r of data.employees) g.set(r.pod, [...(g.get(r.pod) ?? []), r])
    return [...g.entries()]
  }, [data.employees])
  return (
    <div className="max-h-[calc(100vh-15rem)] overflow-auto rounded-lg border bg-background" data-testid="roster-grid">
      <table className="border-separate border-spacing-0 text-sm">
        <DayHeader days={data.days} holidays={holidays} onDayClick={h.onDayClick} label="Employee" />
        <tbody>
          {groups.map(([pod, rows]) => (
            <Fragment key={pod}>
              {groups.length > 1 && (
                <tr>
                  <td colSpan={data.days.length + 1} className="sticky left-0 border-b bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
                    {pod}
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr key={r.employee_id}>
                  <th scope="row" className="sticky left-0 z-10 border-r border-b bg-background px-3 py-1 text-left font-normal">
                    <div className="flex items-center gap-2">
                      <span className="grid size-7 shrink-0 place-items-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
                        {initials(r.name)}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{r.name}{r.is_lead && <span className="ml-1 text-[10px] font-semibold text-blue-600">LEAD</span>}</p>
                        <p className="text-[11px] text-muted-foreground tabular">
                          {r.code} · {r.totals.WORK ?? 0} work · {(r.totals.WEEKLY_OFF ?? 0)} off
                          {r.totals.LEAVE ? ` · ${r.totals.LEAVE} leave` : ''}
                        </p>
                      </div>
                    </div>
                  </th>
                  {r.cells.map((c, i) => (
                    <EntryCell
                      key={data.days[i]}
                      row={r}
                      c={c}
                      holiday={holidays[data.days[i]]}
                      highlight={!!highlight && highlight.employeeId === r.employee_id && highlight.date === data.days[i]}
                      onClick={c ? () => h.onCellClick?.(r, c) : undefined}
                    />
                  ))}
                </tr>
              ))}
            </Fragment>
          ))}
          {showCoverage && data.coverage.length > 0 && <CoverageRows rows={data.coverage} days={data.days} onCoverageClick={h.onCoverageClick} />}
        </tbody>
      </table>
    </div>
  )
}

/** Process view: one row per brand-process shift; cells list who is staffed (derived from duties). */
export function ProcessGrid({ data, holidays, ...h }: GridHandlers & { data: RosterView; holidays: Record<string, string> }) {
  const staffed = useMemo(() => {
    const m = new Map<string, { name: string; backup: boolean }[]>()
    for (const r of data.employees) {
      for (const c of r.cells) {
        if (!c) continue
        for (const d of c.duties) {
          const k = `${d.slot_id}|${c.date}`
          m.set(k, [...(m.get(k) ?? []), { name: r.name, backup: d.duty_type === 'BACKUP' }])
        }
      }
    }
    return m
  }, [data.employees])
  return (
    <div className="max-h-[calc(100vh-15rem)] overflow-auto rounded-lg border bg-background" data-testid="process-grid">
      <table className="border-separate border-spacing-0 text-sm">
        <DayHeader days={data.days} holidays={holidays} onDayClick={h.onDayClick} label="Brand · process · shift" />
        <tbody>
          {data.coverage.map((r) => (
            <tr key={r.slot_id}>
              <th scope="row" className="sticky left-0 z-10 border-r border-b bg-background px-3 py-1 text-left text-xs font-medium">
                <span className="block truncate">{r.brand}</span>
                <span className="text-[11px] font-normal text-muted-foreground">{r.process} · {r.shift}</span>
              </th>
              {r.cells.map((c, i) => {
                const who = staffed.get(`${r.slot_id}|${data.days[i]}`) ?? []
                const s = c ? SLOT_STYLE[c.status] : null
                return (
                  <td key={data.days[i]} className={cn(DAY_W, 'border-b p-0.5')}>
                    {c && (
                      <button
                        type="button"
                        onClick={() => h.onCoverageClick?.(r, data.days[i])}
                        disabled={c.status === 'NOT_REQUIRED'}
                        title={`${r.label} — ${c.date}\n${s!.label} ${c.staffed}/${c.required}\n${who.map((w) => `• ${w.name}${w.backup ? ' (backup)' : ''}`).join('\n')}`}
                        className={cn('flex h-9 w-full flex-col items-center justify-center rounded text-[10px] leading-tight font-semibold', s!.cell)}
                      >
                        {c.status === 'NOT_REQUIRED' ? '·' : who.length ? who.map((w) => (
                          <span key={w.name} className={cn(w.backup && 'underline decoration-dotted')}>{initials(w.name)}</span>
                        )).slice(0, 2) : '—'}
                      </button>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {(['MOR', 'GEN', 'EVE', 'NGT'] as const).map((s) => (
        <span key={s} className="flex items-center gap-1.5"><span className={cn('rounded border px-1 text-[10px] font-semibold', SHIFT_STYLE[s])}>{s}</span>shift</span>
      ))}
      {(['WEEKLY_OFF', 'LEAVE', 'COMP_OFF', 'HOLIDAY', 'UNAVAILABLE'] as const).map((s) => (
        <span key={s} className="flex items-center gap-1.5"><span className={cn('rounded border px-1 text-[10px] font-semibold', ENTRY_STYLE[s].cell)}>{ENTRY_STYLE[s].short}</span>{ENTRY_STYLE[s].label}</span>
      ))}
      <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-amber-500" />backup duty</span>
      <span className="flex items-center gap-1.5"><Lock className="size-3" />manual edit</span>
      <span className="mx-1 h-4 w-px bg-border" />
      {(['MET', 'UNDERSTAFFED', 'UNCOVERED', 'NOT_REQUIRED'] as const).map((s) => (
        <span key={s} className="flex items-center gap-1.5"><span className={cn('size-3 rounded-sm', SLOT_STYLE[s].cell)} />{SLOT_STYLE[s].label}</span>
      ))}
    </div>
  )
}
