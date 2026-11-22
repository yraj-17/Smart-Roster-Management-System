import { useMemo, useState } from 'react'
import { Pencil, Plus, UserX } from 'lucide-react'
import { api } from '@/lib/api'
import { DOW } from '@/lib/format'
import type { Employee, OffDay } from '@/lib/types'
import { useApiMutation, useAssignments, useCalendars, useEmployees, usePods, usePolicies } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Pill, Spinner } from '@/components/common'

const MASTER_KEYS = [['master'], ['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['audit']]

export function EmployeesPage() {
  const q = useEmployees()
  const pods = usePods()
  const policies = usePolicies()
  const assignments = useAssignments()
  const [search, setSearch] = useState('')
  const [pod, setPod] = useState('')
  const [editing, setEditing] = useState<Employee | 'new' | null>(null)
  const podName = useMemo(() => new Map((pods.data ?? []).map((p) => [p.id, p.name])), [pods.data])
  const policyName = useMemo(() => new Map((policies.data ?? []).map((p) => [p.id, p.name])), [policies.data])
  const today = new Date().toISOString().slice(0, 10)
  const counts = useMemo(() => {
    const m = new Map<number, { p: number; b: number }>()
    for (const a of assignments.data ?? []) {
      if (a.effective_to && a.effective_to < today) continue
      const c = m.get(a.employee_id) ?? { p: 0, b: 0 }
      if (a.role === 'PRIMARY') c.p++; else c.b++
      m.set(a.employee_id, c)
    }
    return m
  }, [assignments.data, today])
  const deactivate = useApiMutation((e: Employee) => api.del(`/employees/${e.id}`), { invalidate: MASTER_KEYS, success: 'Employee deactivated' })
  const rows = (q.data ?? []).filter((e) => (!pod || e.pod_id === Number(pod)) &&
    (!search || `${e.name} ${e.code} ${e.email}`.toLowerCase().includes(search.toLowerCase())))

  return (
    <>
      <PageHeader title="Employees" description="Who can be rostered, their pod, rest policy, load cap and weekly-off preferences. FIXED offs are hard rules; PREFERRED offs are soft."
        actions={<Button onClick={() => setEditing('new')}><Plus />Add employee</Button>} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Search name, code, email" value={search} onChange={(e) => setSearch(e.target.value)} />
        <NativeSelect className="w-44" value={pod} onChange={(e) => setPod(e.target.value)} aria-label="Pod">
          <option value="">All pods</option>
          {(pods.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </NativeSelect>
      </div>
      {q.isLoading ? <Loading rows={8} /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : !rows.length ? <EmptyState title="No employees match" /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Employee</TableHead><TableHead>Pod</TableHead><TableHead>Rest policy</TableHead><TableHead className="text-right">Load cap</TableHead>
              <TableHead>Off days</TableHead><TableHead className="text-right">Assignments</TableHead><TableHead /><TableHead className="text-right">Actions</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.map((e) => (
                <TableRow key={e.id} className={e.active ? '' : 'opacity-50'}>
                  <TableCell><p className="font-medium">{e.name}</p><p className="text-xs text-muted-foreground">{e.code} · {e.email}</p></TableCell>
                  <TableCell>{podName.get(e.pod_id)}{pods.data?.find((p) => p.id === e.pod_id)?.lead_employee_id === e.id && <Pill className="ml-1 border-blue-200 bg-blue-50 text-blue-700">lead</Pill>}</TableCell>
                  <TableCell className="text-sm">{policyName.get(e.weekly_off_policy_id)}</TableCell>
                  <TableCell className="text-right tabular">{e.max_daily_load_pct}% <span className="text-xs text-muted-foreground">+{e.backup_stretch_pct}</span></TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {e.off_days.map((o) => (
                        <Pill key={o.day_of_week} className={o.kind === 'FIXED' ? 'border-slate-400 bg-slate-100 text-slate-800' : 'border-dashed border-slate-300 text-slate-600'}
                          title={o.kind === 'FIXED' ? 'Fixed weekly off (hard)' : `Preferred off (soft, priority ${o.priority})`}>
                          {DOW[o.day_of_week]}{o.kind === 'FIXED' ? '' : ` p${o.priority}`}
                        </Pill>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular text-sm">{counts.get(e.id)?.p ?? 0} primary · {counts.get(e.id)?.b ?? 0} backup</TableCell>
                  <TableCell>{!e.active && <Pill className="border-slate-200">inactive</Pill>}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button size="xs" variant="outline" onClick={() => setEditing(e)}><Pencil />Edit</Button>
                      {e.active && <Button size="xs" variant="ghost" onClick={() => deactivate.mutate(e)} title="Deactivate"><UserX /></Button>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing && <EmployeeDialog employee={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function EmployeeDialog({ employee, onClose }: { employee: Employee | null; onClose: () => void }) {
  const pods = usePods()
  const policies = usePolicies()
  const cals = useCalendars()
  const [f, setF] = useState({
    code: employee?.code ?? '', name: employee?.name ?? '', email: employee?.email ?? '',
    pod_id: employee?.pod_id ?? 0, weekly_off_policy_id: employee?.weekly_off_policy_id ?? 0,
    holiday_calendar_id: employee?.holiday_calendar_id ?? null as number | null,
    max_daily_load_pct: employee?.max_daily_load_pct ?? 100, backup_stretch_pct: employee?.backup_stretch_pct ?? 25,
    active: employee?.active ?? true,
  })
  const [offDays, setOffDays] = useState<OffDay[]>(employee?.off_days.map(({ day_of_week, kind, priority }) => ({ day_of_week, kind, priority })) ?? [])
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => {
    const body = { ...f, off_days: offDays }
    return employee ? api.put(`/employees/${employee.id}`, body) : api.post('/employees', body)
  }, { invalidate: MASTER_KEYS, silentError: true, onError: setError, success: employee ? 'Employee updated' : 'Employee added', onSuccess: onClose })
  const setDay = (d: number, kind: '' | 'FIXED' | 'PREFERRED') =>
    setOffDays((cur) => [...cur.filter((o) => o.day_of_week !== d), ...(kind ? [{ day_of_week: d, kind, priority: 2 }] : [])])

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader><DialogTitle>{employee ? `Edit ${employee.name}` : 'Add employee'}</DialogTitle>
          <DialogDescription>Changes flag existing rosters for re-validation.</DialogDescription></DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Code"><Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Email" className="sm:col-span-2"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Pod">
            <NativeSelect value={f.pod_id || ''} onChange={(e) => setF({ ...f, pod_id: Number(e.target.value) })}>
              <option value="" disabled>Select…</option>{(pods.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Rest policy" hint="Minimum weekly offs, max consecutive days, rest hours (hard).">
            <NativeSelect value={f.weekly_off_policy_id || ''} onChange={(e) => setF({ ...f, weekly_off_policy_id: Number(e.target.value) })}>
              <option value="" disabled>Select…</option>{(policies.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Holiday calendar">
            <NativeSelect value={f.holiday_calendar_id ?? ''} onChange={(e) => setF({ ...f, holiday_calendar_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Default calendar</option>{(cals.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </NativeSelect>
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Load cap %"><Input type="number" min={1} max={200} value={f.max_daily_load_pct} onChange={(e) => setF({ ...f, max_daily_load_pct: Number(e.target.value) })} /></Field>
            <Field label="Backup stretch %"><Input type="number" min={0} max={100} value={f.backup_stretch_pct} onChange={(e) => setF({ ...f, backup_stretch_pct: Number(e.target.value) })} /></Field>
          </div>
          <Field label="Weekly-off pattern" className="sm:col-span-2" hint="Fixed = contractual day off (hard). Preferred = honoured when coverage allows (soft).">
            <div className="grid grid-cols-7 gap-1">
              {DOW.map((d, i) => {
                const cur = offDays.find((o) => o.day_of_week === i)?.kind ?? ''
                return (
                  <div key={d} className="text-center">
                    <p className="text-xs font-medium">{d}</p>
                    <NativeSelect className="h-7 px-1 text-xs" value={cur} onChange={(e) => setDay(i, e.target.value as '' | 'FIXED' | 'PREFERRED')}>
                      <option value="">—</option><option value="FIXED">Fixed</option><option value="PREFERRED">Pref.</option>
                    </NativeSelect>
                  </div>
                )
              })}
            </div>
          </Field>
          <div className="sm:col-span-2"><InlineError error={error} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>{save.isPending && <Spinner />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
