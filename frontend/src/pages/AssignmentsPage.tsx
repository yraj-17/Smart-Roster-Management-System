import { useMemo, useState } from 'react'
import { CalendarX2, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import type { Assignment, Role } from '@/lib/types'
import { useApiMutation, useAssignments, useBrandProcesses, useBrands, useEmployees, useProcesses, useShifts, useSlots } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Pill, Spinner } from '@/components/common'

const KEYS = [['master'], ['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['audit']]

function useBpLabels() {
  const bps = useBrandProcesses()
  const brands = useBrands()
  const processes = useProcesses()
  return useMemo(() => {
    const b = new Map((brands.data ?? []).map((x) => [x.id, x.name]))
    const p = new Map((processes.data ?? []).map((x) => [x.id, x.code]))
    return new Map((bps.data ?? []).map((x) => [x.id, `${b.get(x.brand_id)} / ${p.get(x.process_id)}`]))
  }, [bps.data, brands.data, processes.data])
}

export function AssignmentsPage() {
  const q = useAssignments()
  const employees = useEmployees()
  const shifts = useShifts()
  const labels = useBpLabels()
  const [emp, setEmp] = useState('')
  const [role, setRole] = useState('')
  const [search, setSearch] = useState('')
  const [current, setCurrent] = useState(true)
  const [editing, setEditing] = useState<Assignment | 'new' | null>(null)
  const names = useMemo(() => new Map((employees.data ?? []).map((e) => [e.id, e.name])), [employees.data])
  const today = new Date().toISOString().slice(0, 10)
  const rows = (q.data ?? []).filter((a) => (!emp || a.employee_id === Number(emp)) && (!role || a.role === role)
    && (!current || !a.effective_to || a.effective_to >= today)
    && (!search || (labels.get(a.brand_process_id) ?? '').toLowerCase().includes(search.toLowerCase())))
    .sort((a, b) => (labels.get(a.brand_process_id) ?? '').localeCompare(labels.get(b.brand_process_id) ?? '') || a.role.localeCompare(b.role))
  const end = useApiMutation((a: Assignment) => api.put(`/assignments/${a.id}`, { ...a, effective_to: today }), { invalidate: KEYS, success: 'Assignment ended today' })
  const del = useApiMutation((a: Assignment) => api.del(`/assignments/${a.id}`), { invalidate: KEYS, success: 'Assignment deleted' })

  return (
    <>
      <PageHeader title="Assignments" description="Who is responsible for (PRIMARY) or trained to cover (BACKUP) each brand-process, with workload and effective dates. A backup only counts toward coverage once the roster activates a backup duty."
        actions={<Button onClick={() => setEditing('new')}><Plus />Add assignment</Button>} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Input className="w-56" placeholder="Filter brand or process" value={search} onChange={(e) => setSearch(e.target.value)} />
        <NativeSelect className="w-52" value={emp} onChange={(e) => setEmp(e.target.value)} aria-label="Employee">
          <option value="">All employees</option>{(employees.data ?? []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
        </NativeSelect>
        <NativeSelect className="w-32" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
          <option value="">All roles</option><option value="PRIMARY">Primary</option><option value="BACKUP">Backup</option>
        </NativeSelect>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} />Current only</label>
        <span className="text-xs text-muted-foreground">{rows.length} assignments</span>
      </div>
      {q.isLoading ? <Loading rows={10} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : !rows.length ? <EmptyState title="No assignments match" /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow><TableHead>Brand / process</TableHead><TableHead>Employee</TableHead><TableHead>Role</TableHead><TableHead className="text-right">Load</TableHead><TableHead>Shift</TableHead><TableHead>Effective</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {rows.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-medium">{labels.get(a.brand_process_id)}</TableCell>
                  <TableCell>{names.get(a.employee_id)}</TableCell>
                  <TableCell><Pill className={a.role === 'BACKUP' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-blue-200 bg-blue-50 text-blue-700'}>{a.role.toLowerCase()}</Pill></TableCell>
                  <TableCell className="text-right tabular">{a.load_pct}%</TableCell>
                  <TableCell>{a.shift_id ? shifts.data?.find((s) => s.id === a.shift_id)?.code : <span className="text-muted-foreground">any</span>}</TableCell>
                  <TableCell className="text-sm tabular">{fmtDate(a.effective_from, { day: '2-digit', month: 'short', year: '2-digit' })} → {a.effective_to ? fmtDate(a.effective_to, { day: '2-digit', month: 'short', year: '2-digit' }) : 'open'}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button size="xs" variant="outline" onClick={() => setEditing(a)}><Pencil /></Button>
                      {!a.effective_to && <Button size="xs" variant="ghost" onClick={() => end.mutate(a)} title="End today (keeps history)"><CalendarX2 /></Button>}
                      <Button size="xs" variant="ghost" onClick={() => del.mutate(a)} title="Delete (refused if rosters reference it)"><Trash2 /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing && <AssignmentDialog assignment={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function AssignmentDialog({ assignment, onClose }: { assignment: Assignment | null; onClose: () => void }) {
  const employees = useEmployees()
  const slots = useSlots()
  const shifts = useShifts()
  const labels = useBpLabels()
  const [f, setF] = useState({
    employee_id: assignment?.employee_id ?? 0, brand_process_id: assignment?.brand_process_id ?? 0, shift_id: assignment?.shift_id ?? null as number | null,
    role: assignment?.role ?? 'PRIMARY' as Role, load_pct: assignment?.load_pct ?? 50,
    effective_from: assignment?.effective_from ?? new Date().toISOString().slice(0, 10), effective_to: assignment?.effective_to ?? '',
  })
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => {
    const body = { ...f, effective_to: f.effective_to || null }
    return assignment ? api.put(`/assignments/${assignment.id}`, body) : api.post('/assignments', body)
  }, { invalidate: KEYS, silentError: true, onError: setError, success: 'Assignment saved', onSuccess: onClose })
  const bpShifts = (slots.data ?? []).filter((s) => s.brand_process_id === f.brand_process_id).map((s) => s.shift_id)
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{assignment ? 'Edit assignment' : 'Add assignment'}</DialogTitle>
          <DialogDescription>An employee can hold one assignment per brand-process at a time; overlapping dates are rejected.</DialogDescription></DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Employee" className="sm:col-span-2">
            <NativeSelect value={f.employee_id || ''} onChange={(e) => setF({ ...f, employee_id: Number(e.target.value) })}>
              <option value="" disabled>Select…</option>{(employees.data ?? []).filter((e) => e.active).map((e) => <option key={e.id} value={e.id}>{e.name} ({e.code})</option>)}
            </NativeSelect>
          </Field>
          <Field label="Brand / process" className="sm:col-span-2">
            <NativeSelect value={f.brand_process_id || ''} onChange={(e) => setF({ ...f, brand_process_id: Number(e.target.value), shift_id: null })}>
              <option value="" disabled>Select…</option>
              {[...labels.entries()].sort((a, b) => a[1].localeCompare(b[1])).map(([id, l]) => <option key={id} value={id}>{l}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Role">
            <NativeSelect value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}><option value="PRIMARY">Primary</option><option value="BACKUP">Backup (trained cover)</option></NativeSelect>
          </Field>
          <Field label="Load %" hint="Share of a working day this duty takes."><Input type="number" min={1} max={100} value={f.load_pct} onChange={(e) => setF({ ...f, load_pct: Number(e.target.value) })} /></Field>
          <Field label="Shift restriction" className="sm:col-span-2">
            <NativeSelect value={f.shift_id ?? ''} onChange={(e) => setF({ ...f, shift_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Any shift the process runs</option>
              {(shifts.data ?? []).filter((s) => bpShifts.includes(s.id)).map((s) => <option key={s.id} value={s.id}>{s.code} only</option>)}
            </NativeSelect>
          </Field>
          <Field label="From"><Input type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} /></Field>
          <Field label="To (optional)"><Input type="date" value={f.effective_to} min={f.effective_from} onChange={(e) => setF({ ...f, effective_to: e.target.value })} /></Field>
          <div className="sm:col-span-2"><InlineError error={error} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!f.employee_id || !f.brand_process_id || save.isPending}>{save.isPending && <Spinner />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
