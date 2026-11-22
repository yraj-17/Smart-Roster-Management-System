import { useMemo, useState } from 'react'
import { Ban, Check, Plus, RefreshCcw, Trash2, X } from 'lucide-react'
import { api } from '@/lib/api'
import { fmtDate } from '@/lib/format'
import type { ChangeResult, CompOffCredit, Leave } from '@/lib/types'
import { useApiMutation, useCompRequests, useCredits, useEmployees, useLeaves, useUnavailability, useVersion } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState, ErrorState, Field, InlineError, Loading, NativeSelect, PageHeader, Pill, Spinner } from '@/components/common'
import { ReoptimizeDialog } from '@/components/roster/ReoptimizeDialog'

const AVAIL_KEYS = [['leaves'], ['unavailability'], ['credits'], ['comp-requests'], ['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['audit']]

const STATUS_TONE: Record<string, string> = {
  REQUESTED: 'border-amber-200 bg-amber-50 text-amber-800', PENDING: 'border-amber-200 bg-amber-50 text-amber-800',
  APPROVED: 'border-emerald-200 bg-emerald-50 text-emerald-800', AVAILABLE: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  REJECTED: 'border-red-200 bg-red-50 text-red-700', CANCELLED: 'border-slate-200 bg-slate-50 text-slate-500',
  CONSUMED: 'border-blue-200 bg-blue-50 text-blue-800', EXPIRED: 'border-slate-200 bg-slate-50 text-slate-500',
  REVERSED: 'border-slate-200 bg-slate-50 text-slate-500',
}
const tone = (s: string) => <Pill className={STATUS_TONE[s] ?? 'border-slate-200'}>{s.toLowerCase()}</Pill>

function useNames() {
  const e = useEmployees()
  return useMemo(() => new Map((e.data ?? []).map((x) => [x.id, x.name])), [e.data])
}

/** After a change is recorded: which rosters were flagged, with a one-click window repair. */
function ChangeBanner({ result, onDismiss }: { result: ChangeResult; onDismiss: () => void }) {
  const versionId = result.stale_version_ids[result.stale_version_ids.length - 1] ?? null
  const v = useVersion(versionId)
  const [open, setOpen] = useState(false)
  if (!result.stale_version_ids.length) return null
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm" role="status">
      <span className="flex-1">
        Roster version(s) {result.stale_version_ids.map((i) => `#${i}`).join(', ')} were flagged and re-checked.
        {result.reoptimize_hint && <> Repair {fmtDate(result.reoptimize_hint.date_from)}–{fmtDate(result.reoptimize_hint.date_to)} without rebuilding the month.</>}
      </span>
      {result.reoptimize_hint && v.data && <Button size="sm" onClick={() => setOpen(true)}><RefreshCcw />Re-optimise window</Button>}
      <Button size="sm" variant="ghost" onClick={onDismiss}><X /></Button>
      {open && v.data && result.reoptimize_hint && (
        <ReoptimizeDialog version={v.data} defaults={result.reoptimize_hint} onClose={() => { setOpen(false); onDismiss() }} />
      )}
    </div>
  )
}

export function AvailabilityPage() {
  const [change, setChange] = useState<ChangeResult | null>(null)
  return (
    <>
      <PageHeader title="Leave, availability & comp-offs" description="Approvals here immediately flag affected roster versions for re-validation; repair them with a window re-optimisation." />
      {change && <ChangeBanner result={change} onDismiss={() => setChange(null)} />}
      <Tabs defaultValue="leaves">
        <TabsList>
          <TabsTrigger value="leaves">Leaves</TabsTrigger>
          <TabsTrigger value="unavailability">Unavailability</TabsTrigger>
          <TabsTrigger value="compoffs">Comp-offs</TabsTrigger>
        </TabsList>
        <TabsContent value="leaves" className="pt-3"><LeavesTab onChange={setChange} /></TabsContent>
        <TabsContent value="unavailability" className="pt-3"><UnavailabilityTab onChange={setChange} /></TabsContent>
        <TabsContent value="compoffs" className="pt-3"><CompOffsTab onChange={setChange} /></TabsContent>
      </Tabs>
    </>
  )
}

function EmployeeSelect({ value, onChange }: { value: number | null; onChange: (id: number) => void }) {
  const e = useEmployees()
  return (
    <NativeSelect value={value ?? ''} onChange={(ev) => onChange(Number(ev.target.value))}>
      <option value="" disabled>Select…</option>
      {(e.data ?? []).filter((x) => x.active).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.code})</option>)}
    </NativeSelect>
  )
}

function LeavesTab({ onChange }: { onChange: (r: ChangeResult) => void }) {
  const [status, setStatus] = useState('')
  const q = useLeaves(status ? { status } : {})
  const names = useNames()
  const [creating, setCreating] = useState(false)
  const decide = useApiMutation(({ id, action }: { id: number; action: 'approve' | 'reject' | 'cancel' }) =>
    api.post<ChangeResult<Leave>>(`/leaves/${id}/${action}`, {}), {
    invalidate: AVAIL_KEYS, success: (_r, v) => `Leave ${v.action === 'approve' ? 'approved' : v.action === 'reject' ? 'rejected' : 'cancelled'}`,
    onSuccess: (r) => onChange(r),
  })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect aria-label="Status" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {['REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED'].map((s) => <option key={s} value={s}>{s.toLowerCase()}</option>)}
        </NativeSelect>
        <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}><Plus />Request leave</Button>
      </div>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : !q.data?.length ? <EmptyState title="No leave records" /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Dates</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead><TableHead>Reason</TableHead><TableHead>Decided</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {q.data.map((l) => (
                <TableRow key={l.id}>
                  <TableCell className="font-medium">{names.get(l.employee_id)}</TableCell>
                  <TableCell className="tabular">{fmtDate(l.start_date)} – {fmtDate(l.end_date)}</TableCell>
                  <TableCell>{l.leave_type.toLowerCase()}</TableCell>
                  <TableCell>{tone(l.status)}</TableCell>
                  <TableCell className="max-w-48 truncate text-muted-foreground">{l.reason}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{l.decided_by ?? '—'}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      {l.status === 'REQUESTED' && <>
                        <Button size="xs" onClick={() => decide.mutate({ id: l.id, action: 'approve' })} disabled={decide.isPending}><Check />Approve</Button>
                        <Button size="xs" variant="outline" onClick={() => decide.mutate({ id: l.id, action: 'reject' })} disabled={decide.isPending}><X />Reject</Button>
                      </>}
                      {(l.status === 'REQUESTED' || l.status === 'APPROVED') && (
                        <Button size="xs" variant="ghost" onClick={() => decide.mutate({ id: l.id, action: 'cancel' })} disabled={decide.isPending}><Ban />Cancel</Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {creating && <LeaveDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

function LeaveDialog({ onClose }: { onClose: () => void }) {
  const [emp, setEmp] = useState<number | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [type, setType] = useState('PLANNED')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => api.post<Leave>('/leaves', { employee_id: emp, start_date: from, end_date: to, leave_type: type, reason: reason || null }), {
    invalidate: AVAIL_KEYS, silentError: true, onError: setError, success: 'Leave requested — approve it to apply', onSuccess: onClose,
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Request leave</DialogTitle><DialogDescription>Requests do not affect rosters until approved.</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label="Employee"><EmployeeSelect value={emp} onChange={setEmp} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <Field label="Type">
            <NativeSelect value={type} onChange={(e) => setType(e.target.value)}>{['PLANNED', 'SICK', 'CASUAL', 'OTHER'].map((t) => <option key={t} value={t}>{t.toLowerCase()}</option>)}</NativeSelect>
          </Field>
          <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <InlineError error={error} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!emp || !from || !to || save.isPending}>{save.isPending && <Spinner />}Submit request</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function UnavailabilityTab({ onChange }: { onChange: (r: ChangeResult) => void }) {
  const q = useUnavailability()
  const names = useNames()
  const [creating, setCreating] = useState(false)
  const del = useApiMutation((id: number) => api.del<{ stale_version_ids: number[] }>(`/unavailability/${id}`), {
    invalidate: AVAIL_KEYS, success: 'Removed', onSuccess: (r) => onChange({ item: null, stale_version_ids: r.stale_version_ids, reoptimize_hint: null }),
  })
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button size="sm" onClick={() => setCreating(true)}><Plus />Mark unavailable</Button></div>
      {q.isLoading ? <Loading /> : q.isError ? <ErrorState error={q.error} onRetry={q.refetch} /> : !q.data?.length ? <EmptyState title="No unavailability recorded" /> : (
        <div className="overflow-x-auto rounded-lg border bg-background">
          <Table>
            <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Dates</TableHead><TableHead>Reason</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
            <TableBody>
              {q.data.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{names.get(u.employee_id)}</TableCell>
                  <TableCell className="tabular">{fmtDate(u.start_date)} – {fmtDate(u.end_date)}</TableCell>
                  <TableCell className="text-muted-foreground">{u.reason}</TableCell>
                  <TableCell className="text-right"><Button size="xs" variant="ghost" onClick={() => del.mutate(u.id)}><Trash2 />Remove</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {creating && <UnavailabilityDialog onClose={() => setCreating(false)} onChange={onChange} />}
    </div>
  )
}

function UnavailabilityDialog({ onClose, onChange }: { onClose: () => void; onChange: (r: ChangeResult) => void }) {
  const [emp, setEmp] = useState<number | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => api.post<ChangeResult>('/unavailability', { employee_id: emp, start_date: from, end_date: to, reason: reason || null }), {
    invalidate: AVAIL_KEYS, silentError: true, onError: setError, success: 'Unavailability recorded', onSuccess: (r) => { onChange(r); onClose() },
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Mark unavailable</DialogTitle><DialogDescription>Takes effect immediately (training, sickness, other).</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label="Employee"><EmployeeSelect value={emp} onChange={setEmp} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <InlineError error={error} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!emp || !from || !to || save.isPending}>{save.isPending && <Spinner />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CompOffsTab({ onChange }: { onChange: (r: ChangeResult) => void }) {
  const credits = useCredits()
  const requests = useCompRequests()
  const names = useNames()
  const [granting, setGranting] = useState(false)
  const [requesting, setRequesting] = useState<CompOffCredit | null>(null)
  const decideCredit = useApiMutation(({ id, approve }: { id: number; approve: boolean }) =>
    api.post(`/comp-offs/credits/${id}/${approve ? 'approve' : 'reject'}`, {}), { invalidate: AVAIL_KEYS, success: (_d, v) => v.approve ? 'Credit approved' : 'Credit rejected' })
  const decideReq = useApiMutation(({ id, action }: { id: number; action: string }) =>
    api.post<ChangeResult>(`/comp-offs/requests/${id}/${action}`, {}), { invalidate: AVAIL_KEYS, success: (_d, v) => `Request ${v.action}d`.replace('ed d', 'ed'), onSuccess: onChange })
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-semibold">Credits</h2>
            <p className="text-xs text-muted-foreground">Earned automatically when a published roster has someone working a public holiday; approve to make them usable.</p>
          </div>
          <Button size="sm" variant="outline" onClick={() => setGranting(true)}><Plus />Grant</Button>
        </div>
        {credits.isLoading ? <Loading /> : credits.isError ? <ErrorState error={credits.error} /> : !credits.data?.length ? <EmptyState title="No credits" /> : (
          <div className="overflow-x-auto rounded-lg border bg-background">
            <Table>
              <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Earned</TableHead><TableHead>Status</TableHead><TableHead>Expires</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
              <TableBody>
                {credits.data.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell><p className="font-medium">{names.get(c.employee_id)}</p><p className="text-xs text-muted-foreground">{c.note ?? c.source.toLowerCase().replace('_', ' ')}</p></TableCell>
                    <TableCell className="tabular">{fmtDate(c.earned_on)}</TableCell>
                    <TableCell>{tone(c.status)}{c.consumed_on && <span className="ml-1 text-xs text-muted-foreground">on {fmtDate(c.consumed_on)}</span>}</TableCell>
                    <TableCell className="tabular text-muted-foreground">{fmtDate(c.expires_on)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {c.status === 'PENDING' && <>
                          <Button size="xs" onClick={() => decideCredit.mutate({ id: c.id, approve: true })}><Check />Approve</Button>
                          <Button size="xs" variant="outline" onClick={() => decideCredit.mutate({ id: c.id, approve: false })}><X /></Button>
                        </>}
                        {c.status === 'AVAILABLE' && <Button size="xs" variant="outline" onClick={() => setRequesting(c)}>Use…</Button>}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
      <section className="space-y-2">
        <div>
          <h2 className="font-semibold">Requests</h2>
          <p className="text-xs text-muted-foreground">Approving consumes the credit; the day becomes a hard comp-off and affected rosters are re-checked.</p>
        </div>
        {requests.isLoading ? <Loading /> : requests.isError ? <ErrorState error={requests.error} /> : !requests.data?.length ? <EmptyState title="No requests" /> : (
          <div className="overflow-x-auto rounded-lg border bg-background">
            <Table>
              <TableHeader><TableRow><TableHead>Employee</TableHead><TableHead>Day off</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
              <TableBody>
                {requests.data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-medium">{names.get(r.employee_id)}</TableCell>
                    <TableCell className="tabular">{fmtDate(r.date, { weekday: 'short', day: '2-digit', month: 'short' })}</TableCell>
                    <TableCell>{tone(r.status)}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        {r.status === 'REQUESTED' && <>
                          <Button size="xs" onClick={() => decideReq.mutate({ id: r.id, action: 'approve' })}><Check />Approve</Button>
                          <Button size="xs" variant="outline" onClick={() => decideReq.mutate({ id: r.id, action: 'reject' })}><X /></Button>
                        </>}
                        {(r.status === 'REQUESTED' || r.status === 'APPROVED') && <Button size="xs" variant="ghost" onClick={() => decideReq.mutate({ id: r.id, action: 'cancel' })}><Ban /></Button>}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
      {granting && <GrantDialog onClose={() => setGranting(false)} />}
      {requesting && <UseCreditDialog credit={requesting} onClose={() => setRequesting(null)} />}
    </div>
  )
}

function GrantDialog({ onClose }: { onClose: () => void }) {
  const [emp, setEmp] = useState<number | null>(null)
  const [earned, setEarned] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => api.post('/comp-offs/credits', { employee_id: emp, earned_on: earned, note: note || null }), {
    invalidate: AVAIL_KEYS, silentError: true, onError: setError, success: 'Credit granted', onSuccess: onClose,
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Grant comp-off credit</DialogTitle><DialogDescription>Manual grants are available immediately.</DialogDescription></DialogHeader>
        <div className="grid gap-3">
          <Field label="Employee"><EmployeeSelect value={emp} onChange={setEmp} /></Field>
          <Field label="Earned on"><Input type="date" value={earned} onChange={(e) => setEarned(e.target.value)} /></Field>
          <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Covered weekend escalation" /></Field>
          <InlineError error={error} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!emp || !earned || save.isPending}>{save.isPending && <Spinner />}Grant</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function UseCreditDialog({ credit, onClose }: { credit: CompOffCredit; onClose: () => void }) {
  const [day, setDay] = useState('')
  const [error, setError] = useState<unknown>(null)
  const save = useApiMutation(() => api.post('/comp-offs/requests', { employee_id: credit.employee_id, credit_id: credit.id, date: day }), {
    invalidate: AVAIL_KEYS, silentError: true, onError: setError, success: 'Comp-off requested — approve it to apply', onSuccess: onClose,
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Request a comp-off day</DialogTitle><DialogDescription>Uses the credit earned on {fmtDate(credit.earned_on)}; must be on or before {fmtDate(credit.expires_on)}.</DialogDescription></DialogHeader>
        <Field label="Day off"><Input type="date" value={day} max={credit.expires_on ?? undefined} onChange={(e) => setDay(e.target.value)} /></Field>
        <InlineError error={error} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!day || save.isPending}>{save.isPending && <Spinner />}Request</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
