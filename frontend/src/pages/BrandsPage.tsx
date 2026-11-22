import { useMemo, useState } from 'react'
import { Pencil, Plus, Settings2, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { DOW, daysToMask, fmtDate, maskToDays } from '@/lib/format'
import type { Brand, BrandProcess, Process, Shift } from '@/lib/types'
import { cn } from '@/lib/utils'
import {
  useApiMutation, useAssignments, useBrandProcesses, useBrands, useCalendars, useCoverageRequirements, useEmployees,
  useProcesses, useShifts, useSlots,
} from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Pill, Spinner } from '@/components/common'

const KEYS = [['master'], ['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['audit']]

function ruleLabel(bp: BrandProcess) {
  const days = maskToDays(bp.operating_days_mask)
  const all = days.length === 7
  if (all && bp.operates_on_holidays) return '365 days'
  if (all) return 'Daily, holidays off'
  if (bp.operating_days_mask === 0b0111111 && !bp.operates_on_holidays) return 'Mon–Sat, holidays off'
  return `${days.map((d) => DOW[d]).join(' ')}${bp.operates_on_holidays ? ' + holidays' : ''}`
}

export function BrandsPage() {
  return (
    <>
      <PageHeader title="Brands & processes" description="Each brand-process has its own operating calendar, shifts and minimum staffing. Processes and shifts are shared catalogues." />
      <Tabs defaultValue="brands">
        <TabsList><TabsTrigger value="brands">Brands</TabsTrigger><TabsTrigger value="processes">Processes</TabsTrigger><TabsTrigger value="shifts">Shifts</TabsTrigger></TabsList>
        <TabsContent value="brands" className="pt-3"><BrandsTab /></TabsContent>
        <TabsContent value="processes" className="pt-3"><ProcessesTab /></TabsContent>
        <TabsContent value="shifts" className="pt-3"><ShiftsTab /></TabsContent>
      </Tabs>
    </>
  )
}

function BrandsTab() {
  const brands = useBrands()
  const bps = useBrandProcesses()
  const processes = useProcesses()
  const assignments = useAssignments()
  const [editing, setEditing] = useState<Brand | 'new' | null>(null)
  const [configuring, setConfiguring] = useState<Brand | null>(null)
  const proc = useMemo(() => new Map((processes.data ?? []).map((p) => [p.id, p])), [processes.data])
  const today = new Date().toISOString().slice(0, 10)
  const staffOf = (brandId: number) => {
    const ids = new Set((bps.data ?? []).filter((b) => b.brand_id === brandId).map((b) => b.id))
    return new Set((assignments.data ?? []).filter((a) => ids.has(a.brand_process_id) && a.role === 'PRIMARY' && (!a.effective_to || a.effective_to >= today)).map((a) => a.employee_id)).size
  }
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button size="sm" onClick={() => setEditing('new')}><Plus />Add brand</Button></div>
      {brands.isLoading ? <Loading rows={8} /> : brands.isError ? <ErrorState error={brands.error} onRetry={brands.refetch} /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow><TableHead>Brand</TableHead><TableHead>Processes & operating rules</TableHead><TableHead className="text-right">Primary staff</TableHead><TableHead /><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {(brands.data ?? []).map((b) => {
                const staff = staffOf(b.id)
                return (
                  <TableRow key={b.id} className={b.active ? '' : 'opacity-50'}>
                    <TableCell><p className="font-medium">{b.name}</p><p className="text-xs text-muted-foreground">{b.code}{b.notes ? ` · ${b.notes}` : ''}</p></TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(bps.data ?? []).filter((x) => x.brand_id === b.id && x.active).map((x) => (
                          <Pill key={x.id} className="border-slate-200 bg-slate-50 text-slate-700" title={ruleLabel(x)}>
                            <b>{proc.get(x.process_id)?.code}</b><span className="font-normal text-muted-foreground">{ruleLabel(x)}</span>
                          </Pill>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="tabular">{staff}</span>
                      <Pill className={cn('ml-2', staff === 1 ? 'border-slate-200 text-slate-600' : 'border-blue-200 bg-blue-50 text-blue-700')}>{staff === 1 ? 'single-resource' : staff > 1 ? 'multi-resource' : 'unstaffed'}</Pill>
                    </TableCell>
                    <TableCell>{!b.active && <Pill className="border-slate-200">inactive</Pill>}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button size="xs" onClick={() => setConfiguring(b)}><Settings2 />Configure</Button>
                        <Button size="xs" variant="outline" onClick={() => setEditing(b)}><Pencil /></Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
      {editing && <BrandDialog brand={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {configuring && <BrandSheet brand={configuring} onClose={() => setConfiguring(null)} />}
    </div>
  )
}

function BrandDialog({ brand, onClose }: { brand: Brand | null; onClose: () => void }) {
  const cals = useCalendars()
  const [f, setF] = useState({ code: brand?.code ?? '', name: brand?.name ?? '', notes: brand?.notes ?? '', holiday_calendar_id: brand?.holiday_calendar_id ?? null as number | null, active: brand?.active ?? true })
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => brand ? api.put(`/brands/${brand.id}`, f) : api.post('/brands', f), {
    invalidate: KEYS, silentError: true, onError: setError, success: 'Brand saved', onSuccess: onClose,
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{brand ? `Edit ${brand.name}` : 'Add brand'}</DialogTitle><DialogDescription>All processes of a brand share its holiday calendar.</DialogDescription></DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Code"><Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Holiday calendar" className="sm:col-span-2">
            <NativeSelect value={f.holiday_calendar_id ?? ''} onChange={(e) => setF({ ...f, holiday_calendar_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Default calendar</option>{(cals.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Notes" className="sm:col-span-2"><Input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
          <label className="flex items-center gap-2 text-sm"><Switch checked={f.active} onCheckedChange={(v) => setF({ ...f, active: v })} />Active</label>
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

/** Per-brand configuration: processes, operating days, shifts/minimums, overrides, staff. */
function BrandSheet({ brand, onClose }: { brand: Brand; onClose: () => void }) {
  const bps = useBrandProcesses()
  const processes = useProcesses()
  const [adding, setAdding] = useState(false)
  const mine = (bps.data ?? []).filter((b) => b.brand_id === brand.id)
  const used = new Set(mine.map((b) => b.process_id))
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto data-[side=right]:sm:max-w-3xl">
        <SheetHeader><SheetTitle>{brand.name}</SheetTitle><SheetDescription>Operating rules apply to the brand-process; staffing minimums apply per shift.</SheetDescription></SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          {bps.isLoading ? <Loading /> : mine.map((bp) => <BrandProcessCard key={bp.id} bp={bp} process={processes.data?.find((p) => p.id === bp.process_id)} />)}
          {adding ? <AddProcess brand={brand} exclude={used} onDone={() => setAdding(false)} /> : (
            <Button variant="outline" onClick={() => setAdding(true)}><Plus />Add process to {brand.name}</Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function DayToggles({ days, onChange }: { days: number[]; onChange: (d: number[]) => void }) {
  return (
    <div className="flex gap-1">
      {DOW.map((d, i) => (
        <button key={d} type="button" onClick={() => onChange(days.includes(i) ? days.filter((x) => x !== i) : [...days, i])}
          className={cn('w-10 rounded-md border py-1 text-xs font-medium', days.includes(i) ? 'border-blue-600 bg-blue-600 text-white' : 'bg-background text-muted-foreground')}>
          {d}
        </button>
      ))}
    </div>
  )
}

function BrandProcessCard({ bp, process }: { bp: BrandProcess; process?: Process }) {
  const slots = useSlots()
  const shifts = useShifts()
  const reqs = useCoverageRequirements()
  const assignments = useAssignments()
  const employees = useEmployees()
  const [days, setDays] = useState(maskToDays(bp.operating_days_mask))
  const [hol, setHol] = useState(bp.operates_on_holidays)
  const [active, setActive] = useState(bp.active)
  const dirty = daysToMask(days) !== bp.operating_days_mask || hol !== bp.operates_on_holidays || active !== bp.active
  const save = useApiMutation(() => api.put(`/brand-processes/${bp.id}`, { brand_id: bp.brand_id, process_id: bp.process_id, operating_days_mask: daysToMask(days), operates_on_holidays: hol, active }), {
    invalidate: KEYS, success: 'Operating rule saved',
  })
  const mySlots = (slots.data ?? []).filter((s) => s.brand_process_id === bp.id)
  const shiftCode = (id: number) => shifts.data?.find((s) => s.id === id)?.code ?? id
  const today = new Date().toISOString().slice(0, 10)
  const staff = (assignments.data ?? []).filter((a) => a.brand_process_id === bp.id && (!a.effective_to || a.effective_to >= today))
  return (
    <section className={cn('rounded-xl border p-4', !bp.active && 'opacity-60')}>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold">{process?.code} <span className="font-normal text-muted-foreground">— {process?.name}</span></h3>
        <label className="flex items-center gap-2 text-sm"><Switch checked={active} onCheckedChange={setActive} />Active</label>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <Field label="Operating days"><DayToggles days={days} onChange={setDays} /></Field>
        <label className="flex items-center gap-2 pb-1 text-sm"><Switch checked={hol} onCheckedChange={setHol} />Operates on public holidays</label>
        <div className="flex gap-1 pb-0.5">
          {[['365', [0, 1, 2, 3, 4, 5, 6], true], ['Daily', [0, 1, 2, 3, 4, 5, 6], false], ['Mon–Sat', [0, 1, 2, 3, 4, 5], false]].map(([l, d, h]) => (
            <Button key={l as string} size="xs" variant="ghost" onClick={() => { setDays(d as number[]); setHol(h as boolean) }}>{l as string}</Button>
          ))}
        </div>
        <Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate(undefined)}>{save.isPending && <Spinner />}Save rule</Button>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Shifts & minimum staff</p>
          <ul className="space-y-2">
            {mySlots.map((s) => <SlotRow key={s.id} slot={s} code={String(shiftCode(s.shift_id))} reqs={(reqs.data ?? []).filter((r) => r.brand_process_shift_id === s.id)} />)}
          </ul>
          <AddSlot bp={bp} shifts={(shifts.data ?? []).filter((sh) => !mySlots.some((s) => s.shift_id === sh.id))} />
        </div>
        <div>
          <p className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Staff ({staff.length})</p>
          {!staff.length ? <p className="text-sm text-muted-foreground">Nobody assigned — add assignments on the Assignments page.</p> : (
            <ul className="space-y-1 text-sm">
              {staff.map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-2">
                  <span>{employees.data?.find((e) => e.id === a.employee_id)?.name}</span>
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    {a.shift_id && <Pill className="border-slate-200">{shiftCode(a.shift_id)} only</Pill>}
                    <Pill className={a.role === 'BACKUP' ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-slate-200'}>{a.role.toLowerCase()}</Pill>
                    <span className="tabular">{a.load_pct}%</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}

function SlotRow({ slot, code, reqs }: { slot: { id: number; brand_process_id: number; shift_id: number; default_min_staff: number; active: boolean }; code: string; reqs: { id: number; day_of_week: number | null; specific_date: string | null; min_staff: number; reason: string | null }[] }) {
  const [min, setMin] = useState(slot.default_min_staff)
  const [ovKind, setOvKind] = useState<'dow' | 'date'>('dow')
  const [ovDow, setOvDow] = useState(5)
  const [ovDate, setOvDate] = useState('')
  const [ovMin, setOvMin] = useState(1)
  const [ovReason, setOvReason] = useState('')
  const saveMin = useApiMutation(() => api.put(`/slots/${slot.id}`, { ...slot, default_min_staff: min }), { invalidate: KEYS, success: `${code} minimum saved` })
  const addOv = useApiMutation(() => api.post('/coverage-requirements', {
    brand_process_shift_id: slot.id, day_of_week: ovKind === 'dow' ? ovDow : null, specific_date: ovKind === 'date' ? ovDate : null, min_staff: ovMin, reason: ovReason || null,
  }), { invalidate: KEYS, success: 'Override added', onSuccess: () => setOvReason('') })
  const delOv = useApiMutation((id: number) => api.del(`/coverage-requirements/${id}`), { invalidate: KEYS, success: 'Override removed' })
  return (
    <li className="rounded-lg border p-2">
      <div className="flex items-center gap-2">
        <Pill className="border-slate-300 font-semibold">{code}</Pill>
        <span className="text-sm">default minimum</span>
        <Input type="number" min={0} max={50} value={min} onChange={(e) => setMin(Number(e.target.value))} className="h-7 w-16" />
        <Button size="xs" variant="outline" disabled={min === slot.default_min_staff || saveMin.isPending} onClick={() => saveMin.mutate(undefined)}>Save</Button>
      </div>
      {reqs.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs">
          {reqs.map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded bg-muted/60 px-2 py-1">
              <span>{r.day_of_week !== null ? `Every ${DOW[r.day_of_week]}` : fmtDate(r.specific_date, { day: '2-digit', month: 'short', year: 'numeric' })}: <b>{r.min_staff}</b>{r.reason ? ` — ${r.reason}` : ''}</span>
              <Button size="icon-xs" variant="ghost" onClick={() => delOv.mutate(r.id)} aria-label="Remove override"><Trash2 /></Button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <NativeSelect className="h-7 w-24" value={ovKind} onChange={(e) => setOvKind(e.target.value as 'dow' | 'date')}><option value="dow">Weekday</option><option value="date">Date</option></NativeSelect>
        {ovKind === 'dow' ? (
          <NativeSelect className="h-7 w-20" value={ovDow} onChange={(e) => setOvDow(Number(e.target.value))}>{DOW.map((d, i) => <option key={d} value={i}>{d}</option>)}</NativeSelect>
        ) : <Input type="date" className="h-7 w-36" value={ovDate} onChange={(e) => setOvDate(e.target.value)} />}
        <Input type="number" min={0} className="h-7 w-14" value={ovMin} onChange={(e) => setOvMin(Number(e.target.value))} title="Minimum staff" />
        <Input className="h-7 w-32" placeholder="Reason" value={ovReason} onChange={(e) => setOvReason(e.target.value)} />
        <Button size="xs" variant="outline" disabled={addOv.isPending || (ovKind === 'date' && !ovDate)} onClick={() => addOv.mutate(undefined)}><Plus />Override</Button>
      </div>
    </li>
  )
}

function AddSlot({ bp, shifts }: { bp: BrandProcess; shifts: Shift[] }) {
  const [shift, setShift] = useState<number | null>(null)
  const [min, setMin] = useState(1)
  const add = useApiMutation(() => api.post('/slots', { brand_process_id: bp.id, shift_id: shift, default_min_staff: min }), { invalidate: KEYS, success: 'Shift added', onSuccess: () => setShift(null) })
  if (!shifts.length) return null
  return (
    <div className="mt-2 flex items-center gap-1.5 text-xs">
      <NativeSelect className="h-7 w-28" value={shift ?? ''} onChange={(e) => setShift(Number(e.target.value))}>
        <option value="" disabled>Add shift…</option>{shifts.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}
      </NativeSelect>
      <Input type="number" min={0} className="h-7 w-14" value={min} onChange={(e) => setMin(Number(e.target.value))} />
      <Button size="xs" variant="outline" disabled={!shift || add.isPending} onClick={() => add.mutate(undefined)}><Plus />Add</Button>
    </div>
  )
}

function AddProcess({ brand, exclude, onDone }: { brand: Brand; exclude: Set<number>; onDone: () => void }) {
  const processes = useProcesses()
  const [pid, setPid] = useState<number | null>(null)
  const [error, setError] = useState<unknown>(null)
  const add = useApiMutation(() => api.post('/brand-processes', { brand_id: brand.id, process_id: pid, operating_days_mask: 0b0111111, operates_on_holidays: false }), {
    invalidate: KEYS, silentError: true, onError: setError, success: 'Process added — now add shifts and staff', onSuccess: onDone,
  })
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3">
      <NativeSelect className="w-56" value={pid ?? ''} onChange={(e) => setPid(Number(e.target.value))}>
        <option value="" disabled>Choose process…</option>
        {(processes.data ?? []).filter((p) => p.active && !exclude.has(p.id)).map((p) => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
      </NativeSelect>
      <Button size="sm" disabled={!pid || add.isPending} onClick={() => add.mutate(undefined)}>Add</Button>
      <Button size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
      <InlineError error={error} />
    </div>
  )
}

function ProcessesTab() {
  const q = useProcesses()
  const [editing, setEditing] = useState<Process | 'new' | null>(null)
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button size="sm" onClick={() => setEditing('new')}><Plus />Add process</Button></div>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : !q.data?.length ? <EmptyState title="No processes" /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Name</TableHead><TableHead>Description</TableHead><TableHead /><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {q.data.map((p) => (
                <TableRow key={p.id} className={p.active ? '' : 'opacity-50'}>
                  <TableCell className="font-semibold">{p.code}</TableCell><TableCell>{p.name}</TableCell>
                  <TableCell className="text-muted-foreground">{p.description}</TableCell>
                  <TableCell>{!p.active && <Pill className="border-slate-200">inactive</Pill>}</TableCell>
                  <TableCell className="text-right"><Button size="xs" variant="outline" onClick={() => setEditing(p)}><Pencil />Edit</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing && <SimpleDialog title={editing === 'new' ? 'Add process' : `Edit ${editing.code}`} path={editing === 'new' ? '/processes' : `/processes/${editing.id}`} method={editing === 'new' ? 'post' : 'put'}
        fields={[['code', 'Code'], ['name', 'Name'], ['description', 'Description']]}
        initial={editing === 'new' ? { code: '', name: '', description: '', active: true } : { ...editing }} onClose={() => setEditing(null)} />}
    </div>
  )
}

function ShiftsTab() {
  const q = useShifts()
  const [editing, setEditing] = useState<Shift | 'new' | null>(null)
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button size="sm" onClick={() => setEditing('new')}><Plus />Add shift</Button></div>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow><TableHead>Code</TableHead><TableHead>Name</TableHead><TableHead>Hours</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {(q.data ?? []).map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-semibold">{s.code}</TableCell><TableCell>{s.name}</TableCell>
                  <TableCell className="tabular">{s.start_time.slice(0, 5)}–{s.end_time.slice(0, 5)}{s.end_time < s.start_time && <span className="ml-1 text-xs text-muted-foreground">(crosses midnight)</span>}</TableCell>
                  <TableCell className="text-right"><Button size="xs" variant="outline" onClick={() => setEditing(s)}><Pencil />Edit</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {editing && <SimpleDialog title={editing === 'new' ? 'Add shift' : `Edit ${editing.code}`} path={editing === 'new' ? '/shifts' : `/shifts/${editing.id}`} method={editing === 'new' ? 'post' : 'put'}
        fields={[['code', 'Code'], ['name', 'Name'], ['start_time', 'Start', 'time'], ['end_time', 'End', 'time']]}
        initial={editing === 'new' ? { code: '', name: '', start_time: '09:00', end_time: '18:00' } : { ...editing, start_time: editing.start_time.slice(0, 5), end_time: editing.end_time.slice(0, 5) }}
        onClose={() => setEditing(null)} />}
    </div>
  )
}

function SimpleDialog({ title, path, method, fields, initial, onClose }: {
  title: string; path: string; method: 'post' | 'put'; fields: [string, string, string?][]; initial: Record<string, unknown>; onClose: () => void
}) {
  const [f, setF] = useState<Record<string, unknown>>(initial)
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => {
    const body = Object.fromEntries(Object.entries(f).filter(([k]) => k !== 'id'))
    return method === 'post' ? api.post(path, body) : api.put(path, body)
  }, { invalidate: KEYS, silentError: true, onError: setError, success: 'Saved', onSuccess: onClose })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        <div className="grid gap-3">
          {fields.map(([k, label, type]) => (
            <Field key={k} label={label}><Input type={type ?? 'text'} value={String(f[k] ?? '')} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>
          ))}
          <InlineError error={error} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>{save.isPending && <Spinner />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
