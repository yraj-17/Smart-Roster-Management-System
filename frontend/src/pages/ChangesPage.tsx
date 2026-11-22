import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, Eye, RefreshCcw, ShieldAlert, UserMinus } from 'lucide-react'
import { api } from '@/lib/api'
import { usePlan } from '@/lib/plan'
import { fmtDate, fmtPct, iso, lastDay } from '@/lib/format'
import { ACTION_LABEL, SLOT_STYLE } from '@/lib/status'
import type { ChangeResult, Impact, Leave, Version } from '@/lib/types'
import { cn } from '@/lib/utils'
import { useApiMutation, useEmployees, useLeaves, useVersion } from '@/hooks/queries'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { EmptyState, Field, InlineError, Loading, NativeSelect, PageHeader, Pill, Spinner, ValidationBadge } from '@/components/common'
import { ReoptimizeDialog } from '@/components/roster/ReoptimizeDialog'

type Kind = 'LEAVE' | 'UNAVAILABLE'

function Step({ n, title, active, done, children }: { n: number; title: string; active: boolean; done: boolean; children: React.ReactNode }) {
  return (
    <section className={cn('rounded-xl border bg-card p-4 transition-opacity', !active && !done && 'opacity-50')}>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
        <span className={cn('grid size-6 place-items-center rounded-full text-xs', done ? 'bg-emerald-600 text-white' : active ? 'bg-blue-600 text-white' : 'bg-muted text-muted-foreground')}>
          {done ? '✓' : n}
        </span>
        {title}
      </h2>
      {children}
    </section>
  )
}

export function ChangesPage() {
  const { year, month, version, setVersionId } = usePlan()
  const employees = useEmployees()
  const pending = useLeaves({ status: 'REQUESTED' })
  const first = iso(year, month, 1)
  const [empId, setEmpId] = useState<number | null>(null)
  const [from, setFrom] = useState(first)
  const [to, setTo] = useState(first)
  const [kind, setKind] = useState<Kind>('LEAVE')
  const [leaveType, setLeaveType] = useState('PLANNED')
  const [reason, setReason] = useState('')
  const [impact, setImpact] = useState<Impact | null>(null)
  const [recorded, setRecorded] = useState<ChangeResult | null>(null)
  const [pendingLeaveId, setPendingLeaveId] = useState<number | null>(null)
  const [reopt, setReopt] = useState(false)
  const [newVersion, setNewVersion] = useState<Version | null>(null)
  const [error, setError] = useState<unknown>(null)
  const names = useMemo(() => new Map((employees.data ?? []).map((e) => [e.id, e.name])), [employees.data])
  const staleId = recorded?.stale_version_ids.includes(version?.id ?? -1) ? version!.id : recorded?.stale_version_ids[0] ?? null
  const staleVersion = useVersion(staleId)  // reading it triggers re-validation server-side

  const reset = () => { setImpact(null); setRecorded(null); setNewVersion(null); setError(null); setPendingLeaveId(null) }

  const preview = useApiMutation(
    (p: { employee_id: number; date_from: string; date_to: string }) => api.post<Impact>('/impact-preview', p),
    { invalidate: [], silentError: true, onError: setError, onSuccess: (r) => { setImpact(r); setRecorded(null); setNewVersion(null) } },
  )
  const record = useApiMutation(async () => {
    if (pendingLeaveId) return api.post<ChangeResult>(`/leaves/${pendingLeaveId}/approve`, { reason: 'Approved after impact review' })
    if (kind === 'LEAVE') {
      const lv = await api.post<Leave>('/leaves', { employee_id: empId, start_date: from, end_date: to, leave_type: leaveType, reason: reason || null })
      return api.post<ChangeResult>(`/leaves/${lv.id}/approve`, { reason: 'Approved after impact review' })
    }
    return api.post<ChangeResult>('/unavailability', { employee_id: empId, start_date: from, end_date: to, reason: reason || null })
  }, {
    invalidate: [['versions'], ['version'], ['roster'], ['conflicts'], ['dashboard'], ['leaves'], ['unavailability'], ['audit']],
    silentError: true, onError: setError,
    success: (r) => r.stale_version_ids.length ? `Change recorded · ${r.stale_version_ids.length} roster version(s) flagged for re-check` : 'Change recorded (no roster affected)',
    onSuccess: setRecorded,
  })
  const reject = useApiMutation((id: number) => api.post(`/leaves/${id}/reject`, { reason: 'Rejected after impact review' }), {
    invalidate: [['leaves'], ['dashboard'], ['audit']], success: 'Leave request rejected', onSuccess: reset,
  })

  const runPreview = (e: number, d1: string, d2: string) => {
    setError(null)
    preview.mutate({ employee_id: e, date_from: d1, date_to: d2 })
  }
  const loadPending = (lv: Leave) => {
    reset()
    setEmpId(lv.employee_id); setFrom(lv.start_date); setTo(lv.end_date); setKind('LEAVE'); setLeaveType(lv.leave_type)
    setPendingLeaveId(lv.id)
    runPreview(lv.employee_id, lv.start_date, lv.end_date)
  }
  const m = impact?.months[0]
  const step = newVersion ? 5 : recorded ? 4 : impact ? 3 : 2

  return (
    <>
      <PageHeader title="Change management"
        description="When someone becomes unavailable after the roster exists: preview the damage, record the change, and repair only the affected days — without rebuilding the month." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-4">
          <Step n={1} title="Describe the change" active done={!!impact}>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
              <Field label="Employee" className="lg:col-span-2">
                <NativeSelect value={empId ?? ''} onChange={(e) => { reset(); setEmpId(Number(e.target.value)) }} data-testid="change-employee">
                  <option value="" disabled>Select employee…</option>
                  {(employees.data ?? []).filter((e) => e.active).map((e) => <option key={e.id} value={e.id}>{e.name} ({e.code})</option>)}
                </NativeSelect>
              </Field>
              <Field label="From"><Input type="date" value={from} onChange={(e) => { reset(); setFrom(e.target.value); if (e.target.value > to) setTo(e.target.value) }} data-testid="change-from" /></Field>
              <Field label="To"><Input type="date" value={to} min={from} max={iso(year, month, lastDay(year, month))} onChange={(e) => { reset(); setTo(e.target.value) }} data-testid="change-to" /></Field>
              <Field label="Type">
                <NativeSelect value={kind} disabled={!!pendingLeaveId} onChange={(e) => { reset(); setKind(e.target.value as Kind) }}>
                  <option value="LEAVE">Leave</option>
                  <option value="UNAVAILABLE">Unavailable (training, sick, other)</option>
                </NativeSelect>
              </Field>
              {kind === 'LEAVE' && (
                <Field label="Leave type">
                  <NativeSelect value={leaveType} disabled={!!pendingLeaveId} onChange={(e) => setLeaveType(e.target.value)}>
                    {['PLANNED', 'SICK', 'CASUAL', 'OTHER'].map((t) => <option key={t} value={t}>{t.toLowerCase()}</option>)}
                  </NativeSelect>
                </Field>
              )}
              <Field label="Reason" className="lg:col-span-2"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" disabled={!!pendingLeaveId} /></Field>
            </div>
            {pendingLeaveId && <p className="mt-2 text-xs text-muted-foreground">Reviewing pending leave request #{pendingLeaveId}.</p>}
            <div className="mt-3 flex gap-2">
              <Button onClick={() => empId && runPreview(empId, from, to)} disabled={!empId || preview.isPending} data-testid="preview-impact">
                {preview.isPending ? <Spinner /> : <Eye />} Preview impact
              </Button>
              {impact && <Button variant="ghost" onClick={reset}>Start over</Button>}
            </div>
            {!impact && <div className="mt-3"><InlineError error={error} /></div>}
          </Step>

          <Step n={2} title="What-if: impact on the roster" active={step >= 3} done={step > 3}>
            {preview.isPending ? <Loading rows={3} /> : !m ? <p className="text-sm text-muted-foreground">Run a preview to see which shifts would lose cover. Nothing is saved.</p>
              : !m.version_id ? <EmptyState title="No roster for this month" description={m.message} /> : (
                <div className="space-y-4" data-testid="impact-result">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Compared against</p>
                      <p className="font-medium">v{m.version_no} ({m.version_status?.toLowerCase()})</p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Coverage</p>
                      <p className="font-medium tabular">{fmtPct(m.coverage_pct_before, 2)} → <span className={cn((m.coverage_pct_after ?? 0) < (m.coverage_pct_before ?? 0) && 'text-red-600')}>{fmtPct(m.coverage_pct_after, 2)}</span></p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Duties lost</p>
                      <p className="font-medium tabular">{m.duties_lost} · {m.brands_affected?.join(', ') || 'no brand affected'}</p>
                    </div>
                  </div>
                  {m.new_gaps?.length ? (
                    <div>
                      <p className="mb-2 flex items-center gap-1.5 text-sm font-medium"><ShieldAlert className="size-4 text-amber-600" />{m.new_gaps.length} shift(s) would lose cover</p>
                      <ul className="space-y-2">
                        {m.new_gaps.map((g) => (
                          <li key={`${g.slot_id}-${g.date}`} className="rounded-lg border p-3 text-sm">
                            <div className="flex flex-wrap items-center gap-2">
                              <Pill className={SLOT_STYLE[g.status].cell}>{g.staffed}/{g.required}</Pill>
                              <span className="font-medium">{g.label}</span>
                              <span className="text-muted-foreground">{fmtDate(g.date, { weekday: 'short', day: '2-digit', month: 'short' })}</span>
                            </div>
                            <p className="mt-1.5 text-xs text-muted-foreground">
                              {g.suggestions.length ? <>Possible cover: {g.suggestions.map((s) => `${s.name} (${ACTION_LABEL[s.action]?.toLowerCase()})`).join(' · ')}</>
                                : <span className="text-red-700">No eligible replacement — gap will remain unless staffing changes.</span>}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : <p className="flex items-center gap-1.5 text-sm text-emerald-700"><CheckCircle2 className="size-4" />No new gaps — remaining staff keep every required shift covered.</p>}
                </div>
              )}
          </Step>

          <Step n={3} title="Record the change" active={step >= 3} done={step > 3}>
            {!impact ? <p className="text-sm text-muted-foreground">Available after the preview.</p> : recorded ? (
              <div className="space-y-2 text-sm">
                <p className="flex items-center gap-1.5 text-emerald-700"><CheckCircle2 className="size-4" />Recorded and audited.</p>
                {recorded.stale_version_ids.length ? (
                  <p>Roster version(s) {recorded.stale_version_ids.map((id) => `#${id}`).join(', ')} were re-validated against the new availability
                    {staleVersion.data && <> — now <ValidationBadge status={staleVersion.data.validation_status} /></>}.</p>
                ) : <p className="text-muted-foreground">No roster covers these dates.</p>}
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  {pendingLeaveId ? 'Approve the pending request.' : kind === 'LEAVE' ? 'Creates the leave request and approves it.' : 'Marks the employee unavailable.'}
                  {' '}Affected roster versions are flagged and re-checked; nothing is rebuilt automatically.
                </p>
                <div className="flex gap-2">
                  <Button onClick={() => { setError(null); record.mutate(undefined) }} disabled={record.isPending} data-testid="record-change">
                    {record.isPending ? <Spinner /> : <UserMinus />} {pendingLeaveId ? 'Approve leave' : kind === 'LEAVE' ? 'Record & approve leave' : 'Mark unavailable'}
                  </Button>
                  {pendingLeaveId && <Button variant="outline" onClick={() => reject.mutate(pendingLeaveId)} disabled={reject.isPending}>Reject request</Button>}
                </div>
                <InlineError error={error} />
              </div>
            )}
          </Step>

          <Step n={4} title="Repair only the affected days" active={step >= 4} done={step > 4}>
            {!recorded?.reoptimize_hint ? <p className="text-sm text-muted-foreground">Re-optimise the window once the change is recorded.</p> : (
              <div className="space-y-3 text-sm">
                <p>Re-plan <b>{fmtDate(recorded.reoptimize_hint.date_from)} – {fmtDate(recorded.reoptimize_hint.date_to)}</b> for {names.get(recorded.reoptimize_hint.employee_ids[0])} and the people who share their brand-processes. Everything else stays exactly as it is, including manual edits.</p>
                {newVersion ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <CheckCircle2 className="size-4 text-emerald-600" />
                    New draft <b>v{newVersion.version_no}</b> <ValidationBadge status={newVersion.validation_status} /> coverage {fmtPct(newVersion.coverage_pct)}
                    <Link to="/versions" className="ml-2 font-medium text-blue-700 hover:underline">Compare & publish →</Link>
                  </div>
                ) : (
                  <Button onClick={() => setReopt(true)} disabled={!staleVersion.data} data-testid="open-reoptimize"><RefreshCcw /> Re-optimise affected window</Button>
                )}
              </div>
            )}
          </Step>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><CalendarClock className="size-4" />Pending leave requests</CardTitle>
            <CardDescription>Preview the impact before deciding.</CardDescription>
          </CardHeader>
          <CardContent>
            {pending.isLoading ? <Loading rows={3} /> : !pending.data?.length ? <p className="text-sm text-muted-foreground">No pending requests.</p> : (
              <ul className="space-y-2" data-testid="pending-leaves">
                {pending.data.map((lv) => (
                  <li key={lv.id} className={cn('rounded-lg border p-3 text-sm', pendingLeaveId === lv.id && 'border-blue-400 bg-blue-50/50')}>
                    <p className="font-medium">{names.get(lv.employee_id)}</p>
                    <p className="text-xs text-muted-foreground">{fmtDate(lv.start_date)} – {fmtDate(lv.end_date)} · {lv.leave_type.toLowerCase()}{lv.reason ? ` · ${lv.reason}` : ''}</p>
                    <Button size="xs" variant="outline" className="mt-2" onClick={() => loadPending(lv)}><Eye />Review impact</Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      {reopt && staleVersion.data && recorded?.reoptimize_hint && (
        <ReoptimizeDialog
          version={staleVersion.data}
          defaults={{ ...recorded.reoptimize_hint, reason: `${kind === 'LEAVE' ? 'Leave' : 'Unavailability'} for ${names.get(recorded.reoptimize_hint.employee_ids[0])}` }}
          onClose={() => setReopt(false)}
          onDone={(r) => { setNewVersion(r.version); setVersionId(r.version.id) }}
        />
      )}
    </>
  )
}
