import { useMemo, useState } from 'react'
import { RefreshCcw } from 'lucide-react'
import { api } from '@/lib/api'
import { usePlan } from '@/lib/plan'
import { fmtDate, iso, lastDay } from '@/lib/format'
import { VALIDATION_STYLE } from '@/lib/status'
import type { RosterDiff, Version } from '@/lib/types'
import { useApiMutation, useEmployees, useRoster } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field, InlineError, Spinner, ValidationBadge } from '@/components/common'
import { DiffView } from './DiffView'

export interface ReoptResult {
  version: Version
  diff: RosterDiff | null
  lock_conflicts: { employee_id: number; date: string; reason: string }[]
}

export function ReoptimizeDialog({ version, defaults, onClose, onDone }: {
  version: Version
  defaults?: { employee_ids?: number[]; date_from?: string; date_to?: string; reason?: string }
  onClose: () => void
  onDone?: (r: ReoptResult) => void
}) {
  const { setVersionId } = usePlan()
  const employees = useEmployees()
  const roster = useRoster(version.id, 'company', null)
  const first = iso(version.year, version.month, 1)
  const last = iso(version.year, version.month, lastDay(version.year, version.month))
  const [from, setFrom] = useState(defaults?.date_from ?? first)
  const [to, setTo] = useState(defaults?.date_to ?? last)
  const [empIds, setEmpIds] = useState<number[]>(defaults?.employee_ids ?? [])
  const [whole, setWhole] = useState(!defaults?.employee_ids?.length)
  const [overrides, setOverrides] = useState<number[]>([])
  const [reason, setReason] = useState(defaults?.reason ?? '')
  const [result, setResult] = useState<ReoptResult | null>(null)
  const [error, setError] = useState<unknown>(null)

  // Manual rows in the window are kept unless the manager explicitly frees them.
  const manualInWindow = useMemo(() => (roster.data?.employees ?? []).flatMap((r) => r.cells
    .filter((c) => c && c.locked && c.date >= from && c.date <= to)
    .map((c) => ({ entryId: c!.entry_id, name: r.name, date: c!.date }))), [roster.data, from, to])

  const run = useApiMutation(
    () => api.post<ReoptResult>(`/versions/${version.id}/reoptimize`, {
      date_from: from, date_to: to, employee_ids: whole ? null : empIds, whole_window: whole,
      override_manual_entry_ids: overrides, reason: reason || null,
    }),
    {
      silentError: true,
      onError: setError,
      success: (r) => `Re-optimised into v${r.version.version_no}`,
      onSuccess: (r) => { setResult(r); onDone?.(r) },
    },
  )

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{result ? `Result: v${result.version.version_no}` : `Re-optimise v${version.version_no}`}</DialogTitle>
          <DialogDescription>
            {result ? 'A new draft was created. Everything outside the window and scope is identical to the source version.'
              : 'Re-plans only the chosen window. Rows outside it, and manual edits inside it, stay locked. The result is a new draft; the source is untouched.'}
          </DialogDescription>
        </DialogHeader>
        {result ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <ValidationBadge status={result.version.validation_status} />
              <span>Coverage <b className="tabular">{result.version.coverage_pct}%</b> (was {version.coverage_pct}%)</span>
              <span className="text-muted-foreground">{VALIDATION_STYLE[result.version.validation_status].hint}</span>
            </div>
            {result.lock_conflicts.length > 0 && (
              <InlineError error={new Error(`Locked rows block a solution: ${result.lock_conflicts.map((l) => `${l.date} — ${l.reason}`).join('; ')}`)} />
            )}
            {result.diff && <DiffView diff={result.diff} />}
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="From" htmlFor="ro-from"><Input id="ro-from" type="date" min={first} max={last} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
              <Field label="To" htmlFor="ro-to"><Input id="ro-to" type="date" min={first} max={last} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            </div>
            <Field label="Scope" hint={whole ? 'Everyone inside the window may change.' : 'The selected people plus everyone on the brand-processes they touch (and their backups).'}>
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={whole} onCheckedChange={(v) => setWhole(!!v)} />Whole window (all employees)</label>
              {!whole && (
                <div className="max-h-40 overflow-auto rounded-md border p-2">
                  {(employees.data ?? []).filter((e) => e.active).map((e) => (
                    <label key={e.id} className="flex items-center gap-2 py-0.5 text-sm">
                      <Checkbox checked={empIds.includes(e.id)} onCheckedChange={(v) => setEmpIds((c) => v ? [...c, e.id] : c.filter((x) => x !== e.id))} />
                      {e.name} <span className="text-xs text-muted-foreground">{e.code}</span>
                    </label>
                  ))}
                </div>
              )}
            </Field>
            {manualInWindow.length > 0 && (
              <Field label={`Manual edits in window (${manualInWindow.length})`} hint="Kept as-is unless you tick them to let the solver change them.">
                <div className="max-h-32 overflow-auto rounded-md border p-2">
                  {manualInWindow.map((m) => (
                    <label key={m.entryId} className="flex items-center gap-2 py-0.5 text-sm">
                      <Checkbox checked={overrides.includes(m.entryId)} onCheckedChange={(v) => setOverrides((c) => v ? [...c, m.entryId] : c.filter((x) => x !== m.entryId))} />
                      {m.name} · {fmtDate(m.date)}
                    </label>
                  ))}
                </div>
              </Field>
            )}
            <Field label="Reason" htmlFor="ro-reason"><Input id="ro-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Leave approved for Rahul" /></Field>
            <InlineError error={error} />
          </div>
        )}
        <DialogFooter>
          {result ? (
            <>
              <Button variant="outline" onClick={onClose}>Close</Button>
              <Button onClick={() => { setVersionId(result.version.id); onClose() }} data-testid="open-new-version">Open v{result.version.version_no}</Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button disabled={run.isPending || (!whole && !empIds.length) || from > to} onClick={() => { setError(null); run.mutate(undefined) }} data-testid="run-reoptimize">
                {run.isPending ? <Spinner /> : <RefreshCcw />} Re-optimise window
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
