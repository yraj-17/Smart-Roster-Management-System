import { ArrowRight, Minus, Plus } from 'lucide-react'
import { fmtDate } from '@/lib/format'
import { ENTRY_STYLE } from '@/lib/status'
import type { RosterDiff } from '@/lib/types'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { EmptyState, Pill } from '@/components/common'

function statusText(s: { status: keyof typeof ENTRY_STYLE; shift: string | null }) {
  return s.status === 'WORK' ? `Work ${s.shift}` : ENTRY_STYLE[s.status].label
}

export function DiffView({ diff }: { diff: RosterDiff }) {
  const total = diff.changed_entries.length + diff.added_duties.length + diff.removed_duties.length
  if (!total) return <EmptyState title="No differences" description="Both versions assign the same days and duties." />
  return (
    <div className="space-y-4" data-testid="diff-view">
      <div className="flex flex-wrap gap-2 text-sm">
        <Pill className="border-slate-200">{diff.changed_entries.length} day(s) changed</Pill>
        <Pill className="border-emerald-200 bg-emerald-50 text-emerald-800">+{diff.added_duties.length} duties</Pill>
        <Pill className="border-red-200 bg-red-50 text-red-800">−{diff.removed_duties.length} duties</Pill>
      </div>
      {diff.changed_entries.length > 0 && (
        <div className="rounded-lg border">
          <Table>
            <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Date</TableHead><TableHead>Change</TableHead></TableRow></TableHeader>
            <TableBody>
              {diff.changed_entries.map((c) => (
                <TableRow key={`${c.employee_id}-${c.date}`}>
                  <TableCell className="font-medium">{c.employee}</TableCell>
                  <TableCell className="tabular">{fmtDate(c.date, { weekday: 'short', day: '2-digit', month: 'short' })}</TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="text-muted-foreground">{statusText(c.before)}</span>
                      <ArrowRight className="size-3.5" />
                      <span className="font-medium">{statusText(c.after)}</span>
                    </span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {(diff.added_duties.length > 0 || diff.removed_duties.length > 0) && (
        <div className="rounded-lg border">
          <Table>
            <TableHeader><TableRow><TableHead className="w-8" /><TableHead>Employee</TableHead><TableHead>Date</TableHead><TableHead>Duty</TableHead></TableRow></TableHeader>
            <TableBody>
              {[...diff.added_duties.map((d) => ({ ...d, kind: '+' as const })), ...diff.removed_duties.map((d) => ({ ...d, kind: '-' as const }))]
                .sort((a, b) => a.date.localeCompare(b.date) || a.employee.localeCompare(b.employee))
                .map((d) => (
                  <TableRow key={`${d.kind}${d.employee_id}-${d.date}-${d.slot_id}`}>
                    <TableCell>{d.kind === '+' ? <Plus className="size-4 text-emerald-600" /> : <Minus className="size-4 text-red-600" />}</TableCell>
                    <TableCell className="font-medium">{d.employee}</TableCell>
                    <TableCell className="tabular">{fmtDate(d.date)}</TableCell>
                    <TableCell>{d.label}{d.duty_type === 'BACKUP' && <Pill className="ml-1.5 border-amber-200 bg-amber-50 text-amber-800">backup</Pill>}</TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
