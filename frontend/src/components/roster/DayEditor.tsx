import { useMemo, useState } from 'react'
import { Lock, Save } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import { ENTRY_STYLE, VALIDATION_STYLE } from '@/lib/status'
import type { Cell, DayResult, EmployeeRow, EntryStatus, Version } from '@/lib/types'
import { useApiMutation, useAssignments, useBrandProcesses, useBrands, useEmployees, useProcesses, useShifts, useSlots } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field, InlineError, NativeSelect, Pill, Spinner } from '@/components/common'
import { CloneToEdit } from './CloneToEdit'

const STATUSES: EntryStatus[] = ['WORK', 'WEEKLY_OFF', 'LEAVE', 'COMP_OFF', 'HOLIDAY', 'UNAVAILABLE']

export function DayEditor({ version, row, cell, onClose }: {
  version: Version; row: EmployeeRow; cell: Cell; onClose: () => void
}) {
  const assignments = useAssignments()
  const slots = useSlots()
  const bps = useBrandProcesses()
  const brands = useBrands()
  const processes = useProcesses()
  const shifts = useShifts()
  const employees = useEmployees()
  const loading = [assignments, slots, bps, brands, processes, shifts, employees].some((q) => q.isLoading)

  const [status, setStatus] = useState<EntryStatus>(cell.status)
  const [shiftId, setShiftId] = useState<number | null>(cell.shift_id)
  const [selected, setSelected] = useState<number[]>(cell.duties.map((d) => d.slot_id))
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>(null)
  const editable = version.status === 'DRAFT'

  // Options: the slots this employee holds an assignment for on this date (display aid;
  // the API is the authority and rejects anything ineligible with a 409).
  const options = useMemo(() => {
    if (loading) return []
    const bpById = new Map(bps.data!.map((b) => [b.id, b]))
    const brandById = new Map(brands.data!.map((b) => [b.id, b]))
    const procById = new Map(processes.data!.map((p) => [p.id, p]))
    return assignments.data!
      .filter((a) => a.employee_id === row.employee_id && a.effective_from <= cell.date && (!a.effective_to || a.effective_to >= cell.date))
      .flatMap((a) => slots.data!
        .filter((s) => s.brand_process_id === a.brand_process_id && s.active && (a.shift_id === null || a.shift_id === s.shift_id))
        .map((s) => {
          const bp = bpById.get(a.brand_process_id)!
          return { slotId: s.id, shiftId: s.shift_id, role: a.role, load: a.load_pct,
            label: `${brandById.get(bp.brand_id)?.name} / ${procById.get(bp.process_id)?.code}` }
        }))
  }, [loading, assignments.data, slots.data, bps.data, brands.data, processes.data, row.employee_id, cell.date])

  const shiftOptions = useMemo(() => [...new Set(options.map((o) => o.shiftId))], [options])
  const visible = options.filter((o) => o.shiftId === shiftId)
  const emp = employees.data?.find((e) => e.id === row.employee_id)
  const load = visible.filter((o) => selected.includes(o.slotId)).reduce((s, o) => s + o.load, 0)
  const shiftCode = (id: number) => shifts.data?.find((s) => s.id === id)?.code ?? id

  const save = useApiMutation(
    () => api.put<DayResult>(`/versions/${version.id}/entries/${cell.entry_id}`, {
      status,
      shift_id: status === 'WORK' ? shiftId : null,
      slot_ids: status === 'WORK' ? selected.filter((id) => visible.some((o) => o.slotId === id)) : [],
      note: note || null,
    }),
    {
      silentError: true,
      onError: (e) => setError(e),
      onSuccess: (res) => {
        const vs = VALIDATION_STYLE[res.version.validation_status].label
        const issues = res.issues_on_day.filter((i) => i.status === 'OPEN')
        toast.success(`Saved ${row.name} · ${fmtDate(cell.date)}`, {
          description: `Roster is now ${vs.toLowerCase()}${issues.length ? ` · ${issues.length} open issue(s) on this day` : ''}`,
        })
        onClose()
      },
    },
  )

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{row.name} · {fmtDate(cell.date, { weekday: 'long', day: 'numeric', month: 'long' })}</DialogTitle>
          <DialogDescription>
            Replace this day's status and duties. The server validates eligibility, shift and load before saving.
          </DialogDescription>
        </DialogHeader>
        {cell.locked && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Lock className="size-3" />Manually edited — re-optimisation keeps this day unless you override it.</p>
        )}
        {!editable ? (
          <div className="space-y-3">
            <CurrentDay cell={cell} />
            <CloneToEdit version={version} onDone={onClose} />
          </div>
        ) : loading ? <div className="py-6"><Spinner /></div> : (
          <div className="grid gap-4">
            <Field label="Status">
              <div className="flex flex-wrap gap-1.5" role="radiogroup">
                {STATUSES.map((s) => (
                  <button key={s} type="button" role="radio" aria-checked={status === s}
                    onClick={() => { setStatus(s); setError(null); if (s === 'WORK' && shiftId === null) setShiftId(shiftOptions[0] ?? null) }}
                    className={`rounded-md border px-2 py-1 text-xs font-medium ${status === s ? 'border-blue-600 bg-blue-50 text-blue-800' : 'bg-background hover:bg-muted'}`}>
                    {ENTRY_STYLE[s].label}
                  </button>
                ))}
              </div>
            </Field>
            {status === 'WORK' && (
              <>
                <Field label="Shift" hint="An employee works one shift per day; all duties share it.">
                  <NativeSelect value={shiftId ?? ''} onChange={(e) => { setShiftId(Number(e.target.value)); setError(null) }}>
                    {shiftOptions.length === 0 && <option value="">No assignments on this date</option>}
                    {shiftOptions.map((id) => <option key={id} value={id}>{shiftCode(id)}</option>)}
                  </NativeSelect>
                </Field>
                <Field label="Duties" hint={emp ? `Selected load ${load}% · cap ${emp.max_daily_load_pct}% (+${emp.backup_stretch_pct}% for backup duties)` : undefined}>
                  <div className="max-h-56 space-y-1 overflow-auto rounded-md border p-2">
                    {visible.length === 0 && <p className="text-sm text-muted-foreground">No assignments for this shift.</p>}
                    {visible.map((o) => (
                      <label key={o.slotId} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-muted">
                        <Checkbox checked={selected.includes(o.slotId)}
                          onCheckedChange={(v) => { setError(null); setSelected((cur) => v ? [...cur, o.slotId] : cur.filter((x) => x !== o.slotId)) }} />
                        <span className="flex-1">{o.label}</span>
                        <Pill className={o.role === 'BACKUP' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200 bg-slate-50 text-slate-600'}>{o.role.toLowerCase()}</Pill>
                        <span className="w-10 text-right text-xs text-muted-foreground tabular">{o.load}%</span>
                      </label>
                    ))}
                  </div>
                </Field>
              </>
            )}
            <Field label="Note (optional)">
              <input className="h-8 rounded-lg border px-2 text-sm" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder="Why this change?" />
            </Field>
            <InlineError error={error} />
          </div>
        )}
        {editable && (
          <DialogFooter>
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={() => save.mutate(undefined)} disabled={save.isPending || loading} data-testid="save-day">
              {save.isPending ? <Spinner /> : <Save />} Save day
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}

function CurrentDay({ cell }: { cell: Cell }) {
  return (
    <div className="rounded-md border p-3 text-sm">
      <p className="font-medium">{cell.status === 'WORK' ? `Working ${cell.shift}` : ENTRY_STYLE[cell.status].label}</p>
      <ul className="mt-1 space-y-0.5 text-muted-foreground">
        {cell.duties.map((d) => <li key={d.duty_id}>• {d.label}{d.duty_type === 'BACKUP' ? ' (backup)' : ''}</li>)}
      </ul>
    </div>
  )
}
